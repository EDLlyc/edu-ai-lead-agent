# IP 资产登录页 MVP

## Goal

Add a simple, visually complete login page in front of the standalone IP digital-asset platform so
users see a clear entry step before opening the gallery or AI creation studio.

This MVP is a local demonstration gate, not a production authentication or authorization system.

## Confirmed Facts

- The request applies only to the standalone IP asset routes, not the shared development console at
  `/`.
- The protected frontend routes are currently `/ip-assets` and `/ip-assets/create`, including their
  trailing-slash forms.
- The current product uses a browser-local profile token for favorites, uploads, generation jobs,
  and personal results. That mechanism remains unchanged in this MVP.
- The user explicitly does not require professional or strict authentication in the first version;
  having a usable login page and entry flow is the priority.
- There is no reusable application-login implementation in the repository. Avoiding backend,
  database, password hashing, cookie, CORS, and account-migration work keeps this version bounded.

## Requirements

- Add a dedicated standalone `/ip-assets/login` route and page in the existing IP asset visual
  language.
- Accept any username and password after trimming only when both are non-empty. Do not send or store
  either value; successful submission records only a versioned demo-login marker in
  `sessionStorage`.
- Opening either IP asset route without the local demo-login marker must show or redirect to login
  before rendering the asset page.
- After a successful demo login, return the user to the IP route they originally requested.
- Provide visible submit feedback, invalid-form feedback, keyboard operation, focus treatment, and
  a clear loading state.
- Provide a logout action from the IP asset experience; logout clears only the demo-login marker and
  returns to login.
- Preserve the current browser-local material profile and all existing gallery, upload, search,
  favorite, download, personal-library, and AI creation behavior.
- Clearly avoid claiming that the demo gate protects API data or provides verified employee
  identity.

## Key Decisions

- This is a presentation-level local access gate, not authentication.
- Credentials are intentionally not validated against a fixed value: any trimmed non-empty username
  and password can enter.
- Login lasts only for the current browser-tab session. Refresh keeps the session; closing the tab or
  browser ends it according to browser `sessionStorage` behavior.
- The entered credentials are not retained and do not replace the existing browser-local material
  profile.
- The return target is limited to known IP asset routes and safe query strings; invalid or external
  targets fall back to `/ip-assets`.

## Acceptance Criteria

- [x] `/ip-assets` and `/ip-assets/create` do not render their application content before the local
      demo-login condition is satisfied.
- [x] The login page is responsive, keyboard accessible, visually consistent with the IP platform,
      and shows clear feedback for submit and invalid input.
- [x] Successful login restores the originally requested IP route and survives a page refresh for
      the current browser-tab session without storing the entered username or password.
- [x] Logout returns to login without deleting the existing local material profile, favorites, or
      personal-library associations.
- [x] Direct navigation, trailing slashes, malformed return targets, disabled-feature behavior, and
      unknown routes remain deterministic and do not create an open redirect.
- [x] Existing IP asset frontend tests remain green and focused route/login/accessibility tests are
      added.

## Out of Scope

- Backend API authorization or blocking unauthenticated direct API calls.
- Real employee accounts, password hashing, server sessions, SSO, roles, permissions, registration,
  password recovery, account administration, or cross-device identity.
- Rebinding or migrating the existing browser-local personal profile.
- Department workspaces and automated social-platform publishing.

## Planning Note

With the real authentication and data-migration scope removed, this is a lightweight frontend task;
`prd.md` is the complete planning artifact.
