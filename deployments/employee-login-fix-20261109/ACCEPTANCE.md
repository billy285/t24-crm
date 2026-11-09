Employee username login fix deployed

Employee administration exposed login usernames while the login form and authentication service accepted email only. The deployed form and API accept an unambiguous username or email, preserving existing passwords, session checks, employee status checks and roles. All four employee identity mutation paths reject normalized cross-employee username/email collisions.

Source: `9165113c18696690a268e1d13cb0d6149a281649`; deployment carrier: `d968be5e54906d1098fcbba28942aa5202686af6`; frontend: `5521004238f7`. See deployed.json and public-check.json. No migration or production database writes by the release. Full backend inventory verification preserves RingCentral and all unrelated code.

Validation: auth regression81 passed; employee identity/permissions regression96 passed (session coverage overlaps); release helper14 passed independently reviewed; frontend build passed; production database clone startup retained every row and schema object; public version/readiness200; authenticated owner employee page reloaded successfully. The actual employee password was not obtained, changed or used; a real credential sign-in remains for the employee to retry.

Preparation initially stopped on Docker inspect Mounts ordering in both private API and main CRM. Three read-only samples established exact full-configuration equivalence by array permutation. Only complete mount dictionary ordering is normalized for pinned scopes; baseline bytes and prior helpers remain retained. Real configuration, security, identity, image or start-time drift remains rejected. Full clone validation and activation then passed.
