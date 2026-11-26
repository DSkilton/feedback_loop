# Spreadsheet rosters

In the local administrator workspace, choose Roster import, download the CSV template, and enter one membership per row. Both UTF-8 CSV and a single-sheet .xlsx file are supported. All seven columns must be present in the stated order:

| Column | Meaning |
| --- | --- |
| course_id | Existing course identifier from Organisation |
| cohort_id | Stable class identifier (shared by every member of the class) |
| cohort_name | Display name of the class |
| academic_year | e.g. 2026/27 |
| user_id | Stable College account/learner identifier, not a name |
| name | Name corresponding to the account ID |
| member_role | learner or tutor |

Format identifiers as text in Excel, especially IDs with leading zeroes. The preview reports invalid/conflicting rows and planned new/unchanged memberships. Confirm import only after review. The same file hash and current database state are validated again; all changes are committed together or not at all. Import never removes memberships, renames accounts, changes roles, or provisions a tutor account. New learner records are local roster identities, not Microsoft accounts or sign-in permissions; Entra login still requires College-approved identity mapping. A tutor row must refer to an existing approved tutor. Courses must exist before import. Shared courses are created once and mapped to departments separately in Organisation. No direct Teams roster changes are made.

The file is processed in memory (2 MiB / 2,000 rows, bounded workbook expansion); an audit record stores import hash and counts, not spreadsheet contents. Only an explicitly authorised organisation administrator can preview or commit. The local demo must not contain real learner data. Actual College exports may need a separate reviewed column mapping.
