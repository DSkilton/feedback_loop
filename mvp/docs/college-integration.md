# Microsoft integration and deployment

Feedback Loop's core educational rule is unchanged. **Teachers write their own feedback**, students respond and submit evidence of improvement, and **only teachers can close the loop**. We deliberately do not call any AI feedback-generation service.

## 1. Microsoft Entra ID sign-in

The prototype includes an **optional** server-side OIDC authorization-code sign-in using Authlib and PKCE. It is **off unless explicitly enabled**. A verified Microsoft ID token is checked against the exact **tenant ID**, **client ID**, issuer, user object ID, assigned **app role** and an approved identity-to-local-account mapping. Self-registration and automatic teacher promotion are not permitted.

To configure Microsoft sign-in:
1. Register a **single-tenant** web application in Middlesbrough College's Microsoft Entra tenant (not a personal Microsoft account).
2. Add the HTTPS callback, e.g. \`https://example.college.ac.uk/auth/callback\`, as a web redirect URI.
3. Define and assign app roles \`Feedback.Learner\`, \`Feedback.Tutor\` and \`Feedback.Quality\`. Roles are not inferred from names, email domains or display names.
4. Supply a client credential from an approved secret store, not GitHub. Use HTTPS with a trusted reverse proxy; secure session cookies will not work over plain HTTP.
5. Approve and populate learner/tutor account IDs and cohort ownership in the College-controlled database. The current MVP has **no production roster-provisioning workflow**.
6. Provide a College-managed, protected JSON mapping file from each approved Entra **object ID** to an already-enrolled local \`user_id\` and exact role. Example structure with placeholder UUID values:

~~~json
{
  "33333333-3333-4333-8333-333333333333": {
    "user_id": "existing-user-id",
    "role": "tutor"
  }
}
~~~

The mapping contains personal identifiers, must never be committed, and must be readable only by the application service. The \`user_id\` must already exist in the application database and have the same role. The current prototype intentionally **does not auto-create** students or tutors during Microsoft sign-in.

### Configuration

Configuration keys for an approved HTTPS pilot environment:

~~~text
FEEDBACK_LOOP_AUTH_MODE=entra
FEEDBACK_LOOP_ENTRA_TENANT_ID=<approved-tenant-uuid>
FEEDBACK_LOOP_ENTRA_CLIENT_ID=<registered-application-uuid>
FEEDBACK_LOOP_ENTRA_CLIENT_SECRET=<retrieved-from-secret-manager>
FEEDBACK_LOOP_ENTRA_REDIRECT_URI=https://<approved-host>/auth/callback
FEEDBACK_LOOP_SESSION_SECRET=<random-secret-at-least-32-characters>
FEEDBACK_LOOP_ENTRA_ALLOWLIST_PATH=/run/secrets/approved-identity-map.json
~~~

When \`FEEDBACK_LOOP_AUTH_MODE\` is absent and demo mode is not selected, all data APIs deny requests. **Never enable \`FEEDBACK_LOOP_DEMO_MODE=1\` on a public host.** That mode accepts a synthetic demonstration identity header and is explicitly insecure.

After sign-in, the app stores only an approved mapped identity and CSRF token in a signed, HTTPS-only, SameSite cookie, without storing Microsoft Graph access tokens. The OIDC implementation has not yet been tested against the College tenant.

### Deployment checklist

- Secure staff/student provisioning, cohorts, tutor-to-learner assignment validation and offboarding.
- Agree access-control ownership, file retention and audit requirements with the relevant College teams.
- Backend authorization tests against the **real** roster, and a comprehensive penetration review.
- Production secret rotation, session revocation, HTTPS security controls, monitoring, backups and database migrations.
- Accessibility testing for WCAG 2.2 AA with computing learners and screen reader/keyboard users.

## 2. Teams feedback handoff

Initial assessment feedback remains **in Microsoft Teams and Feedback Loop**, as requested. Teachers:
1. Return their own initial feedback through their usual Teams assignment process.
2. Create a feedback action in Feedback Loop, reference the Teams assignment and check **I confirm I have recorded this feedback in Teams**.
3. Add a concise criterion-linked next step and tick **Feedback requires student action**.
4. Continue the student/tutor dialogue in Feedback Loop, view evidence and explicitly close the action.

The system records the tutor's **manual attestation and timestamp**. It does not verify the Teams content, fetch submissions, update grades, or automatically copy feedback.

If actual Graph class, assignment and submission IDs are provided, an exact per-learner unique constraint and API check reject duplicate handoffs. When only a free-text reference is available, full deduplication is not guaranteed.

A future approved Graph read integration could resolve assignments and submitted work using the education API with the minimum appropriate permissions. IT should evaluate delegated \`EduAssignments.ReadBasic\` / \`EduAssignments.Read\` first, rather than asking for tenant-wide read-write access. A true feedback-copy integration would need separate design, consent and permission review; **not implemented here**.

## 3. Evidence upload

Learners can add evidence to their own **in-progress** or **ready-for-review** actions. A tutor can download files for threads they own. A different learner or aggregate-report administrator cannot.

Current implementation:
- PDF, PNG, JPEG or UTF-8 TXT files, verified for basic file signatures.
- Maximum **2 MiB** and **five files** per feedback item.
- Content is stored in the local SQLite database; downloads use authenticated endpoints, not public static links.
- Downloads require per-thread authorization and force attachment disposition.
- Every upload generates a timestamped progress event. The student may also explain what it demonstrates.

**Format validation is not malware scanning.** A hosted deployment needs approved private storage, file scanning, size limits and a retention process.

## 4. Repeated focus areas

The tutor dashboard groups **teacher-entered** development tags per learner across feedback threads. A focus area appears in the recurring panel only after it appears in feedback linked to **at least two distinct assignments**.

This is a **prompt for the tutor to discuss and review**; it is neither AI-inferred feedback nor an automated risk or pastoral judgement. Admin reporting remains aggregate and does not expose the individual focus panel or sensitive pastoral notes.

## 5. Testing and next steps

1. Run \`python -m pytest -q mvp/tests\` and \`node --check mvp/web/app.js\` in CI.
2. Perform a supervised computing learner and tutor usability session.
3. Review manually tested Teams handoff and improve evidence accessibility.
4. Agree deployment architecture, permissions and ownership.
5. Add migrations, roster integration and secure file storage before wider deployment.
