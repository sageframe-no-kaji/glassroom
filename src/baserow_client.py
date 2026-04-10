import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import requests
from dotenv import dotenv_values, set_key

BASE_URL = "http://192.168.1.190:8888"
HOST = "mandala.sageframe.net"
ENV_PATH = Path(".env")

# All fields in creation order. The scraper only writes scraper fields;
# manual and ai_ fields are defined here so the table schema is complete from day one.
FIELD_SPECS: list[dict[str, Any]] = [
    {"name": "assignment_url", "type": "url"},
    {"name": "class_name", "type": "text"},
    {"name": "week_label", "type": "text"},
    {"name": "title", "type": "text"},
    {"name": "description", "type": "long_text"},
    {"name": "teacher", "type": "text"},
    {"name": "posted_date", "type": "date", "date_format": "ISO"},
    {"name": "due_date", "type": "date", "date_format": "ISO"},
    {"name": "points_possible", "type": "number"},
    {"name": "category", "type": "text"},
    {
        "name": "assignment_type",
        "type": "single_select",
        "select_options": [
            {"value": "Assignment", "color": "light-orange"},
            {"value": "Material", "color": "light-blue"},
            {"value": "Quiz", "color": "light-green"},
            {"value": "Question", "color": "light-yellow"},
            {"value": "Unknown", "color": "light-gray"},
        ],
    },
    {
        "name": "status",
        "type": "single_select",
        "select_options": [
            {"value": "Assigned", "color": "light-blue"},
            {"value": "Turned in", "color": "light-green"},
            {"value": "Graded", "color": "light-cyan"},
            {"value": "Missing", "color": "light-red"},
            {"value": "Done", "color": "light-gray"},
            {"value": "Excused", "color": "light-purple"},
            {"value": "Unknown", "color": "light-gray"},
        ],
    },
    {"name": "turn_in_required", "type": "boolean"},
    {"name": "grade", "type": "text"},
    {"name": "attachment_links", "type": "long_text"},
    {"name": "attachment_titles", "type": "long_text"},
    {"name": "scraped_at", "type": "text"},
    {"name": "first_seen_at", "type": "text"},
    {"name": "last_modified_at", "type": "text"},
    # Manual fields — scraper never writes these
    {"name": "class_priority", "type": "number"},
    {"name": "notes", "type": "long_text"},
    # AI agent fields — populated in Ho 4+, scraper never writes these
    {
        "name": "ai_work_type",
        "type": "single_select",
        "select_options": [
            {"value": "Essay", "color": "light-blue"},
            {"value": "Worksheet", "color": "light-yellow"},
            {"value": "Reading", "color": "light-green"},
            {"value": "Quiz/Test", "color": "light-red"},
            {"value": "Project", "color": "light-orange"},
            {"value": "Discussion", "color": "light-purple"},
            {"value": "Busywork", "color": "light-gray"},
            {"value": "Unknown", "color": "dark-gray"},
        ],
    },
    {
        "name": "ai_effort_estimate",
        "type": "single_select",
        "select_options": [
            {"value": "Quick (< 15 min)", "color": "light-green"},
            {"value": "Medium (15-45 min)", "color": "light-yellow"},
            {"value": "Substantial (1+ hr)", "color": "light-red"},
        ],
    },
    {"name": "ai_summary", "type": "text"},
    {"name": "ai_notes", "type": "long_text"},
]

# Fields compared to determine whether a row has actually changed.
# Housekeeping timestamps (scraped_at, first_seen_at, last_modified_at) are excluded
# because they change on every run regardless of content.
COMPARABLE_FIELDS = frozenset(
    {
        "assignment_url",
        "class_name",
        "week_label",
        "title",
        "description",
        "teacher",
        "posted_date",
        "due_date",
        "points_possible",
        "category",
        "assignment_type",
        "status",
        "turn_in_required",
        "grade",
        "attachment_links",
        "attachment_titles",
    }
)


def _parse_date_string(s: str | None) -> str | None:
    """Convert a Google Classroom display date string to ISO YYYY-MM-DD.

    Classroom shows dates in two formats:
      - "Feb 9"        (current year — no year suffix)
      - "Dec 4, 2025"  (prior year — explicit year)

    The "Posted"/"Edited" prefix is stripped if present.
    Returns None if the string is empty, unparseable, or is "No due date".
    """
    if not s:
        return None
    s = re.sub(r"^(Posted|Edited|Updated)\s+", "", s.strip())
    if not s or s.lower().startswith("no "):
        return None
    for fmt in ("%b %d, %Y", "%b %d"):
        try:
            dt = datetime.strptime(s, fmt)
            if fmt == "%b %d":
                dt = dt.replace(year=date.today().year)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Baserow view definitions
# ---------------------------------------------------------------------------

_VIEW_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "Do Now",
        "type": "grid",
        "filters": [
            {"field": "status", "type": "single_select_not_equal", "value": "Turned in"},
            {"field": "status", "type": "single_select_not_equal", "value": "Graded"},
            {"field": "status", "type": "single_select_not_equal", "value": "Done"},
            {"field": "turn_in_required", "type": "boolean", "value": "true"},
        ],
        "sortings": [
            {"field": "due_date", "order": "ASC"},
        ],
        "group_bys": [
            {"field": "class_name", "order": "ASC"},
        ],
    },
    {
        "name": "All by Class",
        "type": "grid",
        "filters": [],
        "sortings": [
            {"field": "due_date", "order": "DESC"},
        ],
        "group_bys": [
            {"field": "class_name", "order": "ASC"},
        ],
    },
    {
        "name": "Needs AI Review",
        "type": "grid",
        "filters": [
            {"field": "ai_work_type", "type": "empty", "value": ""},
        ],
        "sortings": [
            {"field": "class_name", "order": "ASC"},
            {"field": "due_date", "order": "ASC"},
        ],
        "group_bys": [],
    },
]


def _extract_comparable(value: Any) -> Any:
    """Normalize a Baserow response value for equality comparison.

    single_select fields return a dict like {"id": 5, "value": "Assignment", ...}.
    We only care about the value string.

    Number fields are returned as strings by Baserow (e.g. "100" not 100).
    Convert integer-looking strings so they compare equal to Python ints.
    """
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    if isinstance(value, str):
        # Baserow returns number fields as strings (e.g. "100" or "100.0").
        # Normalize to int so they compare equal to the Python ints we write.
        try:
            f = float(value)
            if f == int(f):
                return int(f)
        except ValueError:
            pass
    return value


class BaserowClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
    ) -> None:
        from urllib.parse import urlparse

        self._base_url = (base_url or BASE_URL).rstrip("/")
        self._host = urlparse(self._base_url).netloc if base_url else HOST
        # When a token is passed directly (web UI), skip the .env credential path
        # and don't attempt a JWT refresh on 401 (direct tokens don't rotate).
        self._direct_token = token is not None
        self.session = requests.Session()
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if not base_url:
            # Legacy CLI path: set the Host override for the user's reverse proxy.
            headers["Host"] = HOST
        self.session.headers.update(headers)
        if token:
            self._set_token(token)
        else:
            self._set_token(self._get_token())

    def _set_token(self, token: str) -> None:
        self.token = token
        # Baserow's /api/user/token-auth/ returns a short-lived JWT access token.
        # The correct Authorization prefix for these is "JWT", not "Token".
        # ("Token" is for long-lived database API tokens created in the Baserow UI.)
        self.session.headers["Authorization"] = f"JWT {token}"

    def _auth_with_credentials(self) -> str:
        """Exchange email + password for a fresh JWT access token."""
        env = dotenv_values(ENV_PATH)
        email = (env.get("BASEROW_EMAIL") or "").strip()
        password = (env.get("BASEROW_PASSWORD") or "").strip()
        if not email or not password:
            print("No credentials in .env. Set BASEROW_EMAIL and BASEROW_PASSWORD.")
            sys.exit(1)

        try:
            resp = requests.post(
                f"{self._base_url}/api/user/token-auth/",
                headers={"Host": self._host, "Content-Type": "application/json"},
                json={"email": email, "password": password},
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            print(
                f"Baserow authentication failed: {exc.response.status_code} "
                f"{exc.response.text}"
            )
            sys.exit(1)
        except requests.RequestException as exc:
            print(f"Could not reach Baserow at {self._base_url}: {exc}")
            sys.exit(1)

        token: str = resp.json()["token"]
        set_key(str(ENV_PATH), "BASEROW_TOKEN", token)
        return token

    def _get_token(self) -> str:
        """Return the cached token from .env, or obtain a fresh one via credentials."""
        env = dotenv_values(ENV_PATH)
        token = (env.get("BASEROW_TOKEN") or "").strip()
        if token:
            return token
        return self._auth_with_credentials()

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        resp = self.session.request(method, f"{self._base_url}{path}", **kwargs)
        if resp.status_code in (401, 403):
            if self._direct_token:
                # Direct API tokens don't support JWT refresh; fail immediately.
                raise requests.HTTPError(
                    f"{resp.status_code} {resp.reason} — token rejected",
                    response=resp,
                )
            # JWT access tokens expire in ~10 minutes. Try a fresh auth once before
            # giving up — this handles the common case of a stale cached token.
            print("Token rejected; re-authenticating...")
            self._set_token(self._auth_with_credentials())
            resp = self.session.request(method, f"{self._base_url}{path}", **kwargs)
            if resp.status_code in (401, 403):
                print("Authentication failed. Check BASEROW_EMAIL and BASEROW_PASSWORD in .env.")
                sys.exit(1)
        if not resp.ok:
            raise requests.HTTPError(
                f"{resp.status_code} {resp.reason} — {resp.text[:500]}",
                response=resp,
            )
        return resp

    def setup(
        self, config: dict[str, Any], non_interactive: bool = False
    ) -> dict[str, Any]:
        """Create workspace database, table, and all fields. Idempotent — safe to re-run.

        When non_interactive=True, auto-select the first available workspace instead
        of prompting via input().  Used by the web UI export flow.
        """
        from src.config import save_config

        # 1. Workspace
        if not config.get("baserow_workspace_id"):
            workspaces = self._request("GET", "/api/workspaces/").json()
            if not workspaces:
                print("No workspaces found in Baserow.")
                sys.exit(1)
            if len(workspaces) == 1 or non_interactive:
                workspace = workspaces[0]
            else:
                print("Multiple workspaces found:")
                for i, w in enumerate(workspaces):
                    print(f"  {i + 1}. {w['name']} (id={w['id']})")
                choice = int(input("Select workspace number: ")) - 1
                workspace = workspaces[choice]
            config["baserow_workspace_id"] = workspace["id"]
            print(f"Workspace: {workspace['name']} (id={workspace['id']})")
            save_config(config)
        else:
            print(f"Workspace already set (id={config['baserow_workspace_id']})")

        # 2. Database
        if not config.get("baserow_database_id"):
            resp = self._request(
                "POST",
                f"/api/applications/workspace/{config['baserow_workspace_id']}/",
                json={"name": "CPSD Classroom", "type": "database"},
            )
            db = resp.json()
            config["baserow_database_id"] = db["id"]
            print(f"Created database: {db['name']} (id={db['id']})")
            save_config(config)
        else:
            print(f"Database already exists (id={config['baserow_database_id']})")

        # 3. Table
        if not config.get("baserow_table_id"):
            resp = self._request(
                "POST",
                f"/api/database/tables/database/{config['baserow_database_id']}/",
                json={"name": "Assignments"},
            )
            table = resp.json()
            config["baserow_table_id"] = table["id"]
            print(f"Created table: {table['name']} (id={table['id']})")
            save_config(config)
        else:
            print(f"Table already exists (id={config['baserow_table_id']})")

        # 4. Fields — reconcile against the live table before creating anything.
        # config.json may be stale after a partial run, and Baserow creates a default
        # "Name" field on every new table. GET the real field list and merge it into
        # config first so we never try to create a field that already exists.
        table_id = config["baserow_table_id"]
        live_fields = self._request(
            "GET", f"/api/database/fields/table/{table_id}/"
        ).json()
        field_ids: dict[str, int] = config.get("baserow_field_ids") or {}
        for f in live_fields:
            if f["name"] not in field_ids:
                field_ids[f["name"]] = f["id"]
        config["baserow_field_ids"] = field_ids
        save_config(config)

        for spec in FIELD_SPECS:
            field_name = spec["name"]
            if field_name in field_ids:
                print(f"  Field already exists: {field_name}")
                continue
            resp = self._request(
                "POST",
                f"/api/database/fields/table/{table_id}/",
                json=spec,
            )
            field = resp.json()
            field_ids[field_name] = field["id"]
            config["baserow_field_ids"] = field_ids
            print(f"  Created field: {field_name} (id={field['id']})")
            save_config(config)

        print("Setup complete.")
        return config

    def create_views(self, config: dict[str, Any]) -> None:
        """Create the three dashboard views in the Assignments table.

        Idempotent — skips any view whose name already exists. Filters,
        sortings, and group_bys are only created for new views.
        """
        table_id = config["baserow_table_id"]
        field_ids = config.get("baserow_field_ids") or {}

        existing = self._request(
            "GET", f"/api/database/views/table/{table_id}/"
        ).json()
        existing_names = {v["name"] for v in existing}

        for vdef in _VIEW_DEFINITIONS:
            name = vdef["name"]
            if name in existing_names:
                print(f"  View already exists: {name}")
                continue

            resp = self._request(
                "POST",
                f"/api/database/views/table/{table_id}/",
                json={"name": name, "type": vdef["type"]},
            )
            view_id = resp.json()["id"]
            print(f"  Created view: {name} (id={view_id})")

            for f in vdef.get("filters", []):
                fid = field_ids.get(f["field"])
                if not fid:
                    continue
                try:
                    self._request(
                        "POST",
                        f"/api/database/views/{view_id}/filters/",
                        json={"field": fid, "type": f["type"], "value": f["value"]},
                    )
                except Exception as exc:
                    print(
                        f"    Warning: filter on {f['field']} failed: {exc}",
                        file=sys.stderr,
                    )

            for s in vdef.get("sortings", []):
                fid = field_ids.get(s["field"])
                if not fid:
                    continue
                try:
                    self._request(
                        "POST",
                        f"/api/database/views/{view_id}/sortings/",
                        json={"field": fid, "order": s["order"]},
                    )
                except Exception as exc:
                    print(
                        f"    Warning: sort on {s['field']} failed: {exc}",
                        file=sys.stderr,
                    )

            for g in vdef.get("group_bys", []):
                fid = field_ids.get(g["field"])
                if not fid:
                    continue
                try:
                    self._request(
                        "POST",
                        f"/api/database/views/{view_id}/group_bys/",
                        json={"field": fid, "order": g["order"]},
                    )
                except Exception as exc:
                    print(
                        f"    Warning: group_by on {g['field']} failed: {exc}",
                        file=sys.stderr,
                    )

    def _prepare_field_data(self, field_data: dict[str, Any]) -> dict[str, Any]:
        """Convert scraped values to Baserow-compatible formats before upsert.

        Specifically, date fields (posted_date, due_date) arrive as Classroom
        display strings like "Feb 9" or "Dec 4, 2025". Baserow's ISO date
        fields require YYYY-MM-DD; we parse here before writing.
        """
        prepared = dict(field_data)
        for date_field in ("posted_date", "due_date"):
            prepared[date_field] = _parse_date_string(prepared.get(date_field))
        # Baserow number field defaults to 0 decimal places. Google Classroom
        # always uses whole-number point values, so truncating is safe.
        pts = prepared.get("points_possible")
        if pts is not None:
            prepared["points_possible"] = int(pts)
        return prepared

    def upsert(
        self,
        field_data: dict[str, Any],
        table_id: int,
        field_ids: dict[str, int],
    ) -> Literal["inserted", "updated", "skipped"]:
        """Insert or update a row keyed on assignment_url.

        field_data should contain all scraper fields EXCEPT first_seen_at,
        last_modified_at, and scraped_at — this method manages those timestamps.

        Returns 'inserted', 'updated', or 'skipped'.
        """
        field_data = self._prepare_field_data(field_data)
        url_field_id = field_ids["assignment_url"]
        assignment_url = field_data["assignment_url"]
        now = datetime.now(timezone.utc).isoformat()

        resp = self._request(
            "GET",
            f"/api/database/rows/table/{table_id}/",
            params={f"filter__field_{url_field_id}__equal": assignment_url},
        )
        result = resp.json()

        if result["count"] == 0:
            payload = self._build_payload(field_data, field_ids)
            payload[f"field_{field_ids['first_seen_at']}"] = now
            payload[f"field_{field_ids['last_modified_at']}"] = now
            payload[f"field_{field_ids['scraped_at']}"] = now
            self._request(
                "POST",
                f"/api/database/rows/table/{table_id}/",
                json=payload,
            )
            return "inserted"

        existing = result["results"][0]

        if not self._has_changes(field_data, existing, field_ids):
            return "skipped"

        row_id = existing["id"]
        payload = self._build_payload(field_data, field_ids)
        payload[f"field_{field_ids['scraped_at']}"] = now
        payload[f"field_{field_ids['last_modified_at']}"] = now
        # first_seen_at is intentionally absent from the patch payload
        self._request(
            "PATCH",
            f"/api/database/rows/table/{table_id}/{row_id}/",
            json=payload,
        )
        return "updated"

    def _build_payload(
        self, field_data: dict[str, Any], field_ids: dict[str, int]
    ) -> dict[str, Any]:
        """Translate field_name→value dict to the field_{id}→value format Baserow expects."""
        return {
            f"field_{field_ids[name]}": value
            for name, value in field_data.items()
            if name in field_ids
        }

    def get_all_rows(self, table_id: int) -> list[dict[str, Any]]:
        """Fetch every row in a table, paginating until exhausted."""
        rows: list[dict[str, Any]] = []
        page = 1
        page_size = 200
        while True:
            resp = self._request(
                "GET",
                f"/api/database/rows/table/{table_id}/",
                params={"page": page, "size": page_size},
            )
            data = resp.json()
            rows.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
        return rows

    def _has_changes(
        self,
        new_data: dict[str, Any],
        existing_row: dict[str, Any],
        field_ids: dict[str, int],
    ) -> bool:
        """Return True if any comparable scraper field differs from the stored row."""
        for field_name in COMPARABLE_FIELDS:
            if field_name not in field_ids or field_name not in new_data:
                continue
            field_key = f"field_{field_ids[field_name]}"
            existing_val = _extract_comparable(existing_row.get(field_key))
            new_val = new_data[field_name]
            # Treat None and empty string as equivalent so whitespace-only
            # differences in optional fields don't trigger spurious updates.
            if existing_val in (None, "") and new_val in (None, ""):
                continue
            if existing_val != new_val:
                return True
        return False
