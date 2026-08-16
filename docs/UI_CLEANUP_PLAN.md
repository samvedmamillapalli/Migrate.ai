# UI cleanup & bug-fix plan

Written 2026-08-15. **Plan only — nothing has been changed yet.** When the work
is done it stays **uncommitted in the working tree**, so the live deployment is
untouched until you decide otherwise.

Every item was traced to a real file and line number. Two items turned out not
to be what they looked like — see **2A** and **4A**. Every judgement call has
already been made for you; nothing here is waiting on an answer.

Scope: nothing outside your list gets touched.

---

## Summary

| # | Item | Type | Who |
|---|---|---|---|
| 1 | Strip run ID / owner / SQL filename from run detail | UI | Me |
| 2A | "APPROVED" contradicts "AWAITING APPROVAL" | Label bug | Me |
| 2B | Run detail page looks frozen | UX gap | Me |
| 3A | **"Watch live" does literally nothing** | Real bug | Me |
| 3B | PRED → ACTUAL always expanded | UI | Me |
| 4A | Invited account sees an empty workspace | Permissions change | Me |
| 4B | GitHub 404 | **Settings, not code** | **You** |
| 5 | White triangle favicon + URL as tab title | UI | Me |
| 6 | Past Migrations cluttered | UI | Me |
| 7 | First/last name optional | Clerk setting | **You** |
| 8 | Dashboard "Recent" block + raw SQL | UI | Me |
| 9 | Sign-in email branding | Clerk setting | **You** |
| 10 | Model chatter under progress bar | UI | Me |

---

## 1. Run detail header — remove the clutter

**File:** `apps/web/app/dashboard/migrations/[id]/page.tsx`

| On screen | Line | Source |
|---|---|---|
| `47acd287-6d2e-4ae3-…` under the title | **575** | `{run.id}` |
| `Not started · owner: user_3H5Jg…` | **604–608** | `workflowLabel()` + `run.owner_identity` |
| `migration_47acd287.sql` in the black bar | **615** | `sqlFilename(run.migration_sql, run.id)` |

**Plan**

- Delete the `<p>` containing `{run.id}` (575–576).
- Delete the entire `<p>` at 604–608 — both the workflow label and the owner
  string. The status badge directly above already carries the useful signal.
- SQL panel: `sqlFilename()` (`lib/api/map-run.ts:369-378`) builds a name from
  the first SQL line and falls back to `migration_<8 chars>.sql`. That helper is
  used elsewhere, so it is **not** being changed. Instead the run detail page
  will pass the affected **table name** as the label (e.g. `demo_items`), which
  is genuinely useful, and never the UUID.

Result: title, status badge, SQL. Nothing else.

---

## 2A. "APPROVED" in blue while the badge reads "AWAITING APPROVAL"

**This is a labelling bug, not a data bug** — and that is precisely why it is
confusing. Both halves of the screen were telling the truth.

**File:** `apps/web/lib/api/map-run.ts:1667-1680`

The stage is **named** `"Approved"`, but its state is:

```
state: approved ? "complete"
     : run.status === "awaiting_approval" ? "current"   // ← the blue dot
     : …
```

A **blue "APPROVED"** means *"this is the step we are sitting on, waiting"*, not
*"this was approved"*. The header badge is correct; the timeline is misleading.

**Plan:** make the label depend on state — **"Awaiting approval"** while
`current`, **"Approved"** once `complete`. The two halves stop contradicting
each other, and no other stage is affected.

---

## 2B. The page looks frozen

Run `47acd287` is genuinely still `status = awaiting_approval`,
`workflow_status = not_started`. Nothing has stalled — **it has not been
approved yet**, and the run detail page is read-only: it has no Approve control.
The only way forward is `Set as current migration`, which moves you to the
Current Migration page where approval actually lives.

**Plan:** when a run is awaiting approval, render one line under the status
badge — *"This run needs approval — open it as your current migration to
continue"* — pointing at the button that already exists. Pure affordance, no
backend work.

---

## 3A. "Watch live" does nothing — root cause confirmed

**File:** `apps/web/components/shadow-execution-window.tsx`

```
65-68   PAGES_WITH_OWN_LIVE_SHADOW_VIEW = {
          "/dashboard/migrations/current/shadow",
          "/dashboard/migrations/current",     ← the page the button is on
        }
163     if (!open || !runId || onDedicatedPage) return null
```

The button (`current-migration-workspace.tsx:2324` and `:2355`) calls
`openWatch(run.id)`, which correctly opens the window. The window then renders
**nothing**, because the current page is on the "already has its own live view"
exclusion list. The click is a guaranteed no-op.

Nothing is broken underneath — the button should not be there at all.

**Plan:** remove the "Watch live" button from the two pages that already show
the live view inline, keeping `Open full page`. This matches the original design
intent and deletes a dead control rather than papering over it. The floating
window still works everywhere else (it is what auto-opens when a shadow run
starts while you are on another page).

---

## 3B. Collapse PRED → ACTUAL

The duration / storage / rollback rows sit permanently expanded, and during a
run every value reads `measuring…` — pure noise at the moment you are watching.

**Plan:** wrap the comparisons block in a collapsible titled **"Prediction vs
actual"**, **collapsed by default**, reusing the disclosure pattern already used
elsewhere in the app. It **auto-expands once real numbers land**, so the payoff
moment is never hidden. `EVENT LOG` gets the same treatment while empty.

---

## 4A. Invited account sees an empty workspace

Worth knowing: this is **not a regression**. When invites were built, run access
was deliberately left owner-scoped — an invite added someone to the member
roster but intentionally gave them no access to the workspace's runs, recorded
at the time as a deferred option called *"Full shared access"*.

You have now asked for it to work, so **the plan is to make that change**.

**Files:**

- `backend/app/api/routes/runs.py` — `assert_run_access`, `get_owned_run`,
  `get_owned_run_with_children`
- `backend/app/services/workspace_service.py` — `get_owned_workspace`

**Plan:** access to a run resolves to *"you own it **or** you are a member of the
workspace it belongs to"*. Runs with no workspace stay strictly owner-only, so
nothing becomes visible that was not deliberately placed in a shared workspace.

**Flagging plainly, once:** this widens who can read migration data. It is the
right call given the feature is meant to be collaborative, and it is scoped so
that only runs explicitly attached to a shared workspace become visible. It also
needs the **backend redeployed** to take effect (it is control-plane code, so a
Lightsail redeploy — no SAM build required).

---

## 4B. GitHub 404 — a settings problem, not a code problem

The link is built server-side at `backend/app/services/github_setup.py:47-53`:

```
https://github.com/apps/{app_slug}/installations/new
```

The slug is fetched live from GitHub's own API, so it is neither stale nor
hard-coded. The code is fine.

**The cause: your GitHub App is set to "Only on this account" (private).**
GitHub's documentation is explicit that only **public** apps get a landing page
with an Install button; a private app can only ever be installed on the account
that owns it, so its public install URL 404s for everyone else. For *"any user
can connect their own repo"*, the App must be **public**.

Two different GitHub buttons fail for two different reasons — worth separating:

- **"Install on GitHub →"** (workspace panel) → the install page above → fixed
  by making the App public (**Task 1**).
- **"Connect"** (Settings → GitHub identity) → hits `/api/github/install` and
  redirects to GitHub's OAuth screen → fails when the App's **Callback URL**
  does not exactly match the deployed API URL (**Task 2**).

---

## 5. Favicon and tab title

**Cause:** `apps/web/app/layout.tsx` has **no `metadata` export at all**, so the
tab falls back to the raw URL, and `app/favicon.ico` is still the stock Next.js
icon — the white triangle.

Good news: the real logo is already in the repo at
`apps/web/app/migration-oracle-logo.png` (the sidebar imports it). **Nothing is
needed from you.**

**Plan**

- Add to `app/layout.tsx`:
  ```
  export const metadata = {
    title: "Migration Oracle",
    description: "Predict, verify, grade and remember database migrations.",
  }
  ```
- Add `app/icon.png` generated from the existing logo — Next.js App Router picks
  this up automatically as the favicon — and delete the stock
  `app/favicon.ico` so the triangle cannot win.

Tab becomes **Migration Oracle** with the real mark.

---

## 6. Past Migrations — simplify

**File:** `apps/web/app/dashboard/migrations/history/page.tsx`

| Change | Detail |
|---|---|
| Remove the approver column | And its filter dropdown — state at 157/162, `listApprovers` import at 24, control at ~413 |
| No raw SQL in the table | Replace `SQL / TABLE` with the table name plus a plain migration type ("Add column", "Create index") |
| Drop the time of day | `Aug 8`, not `2026-08-08 08:56 PM` |
| Shrink the accuracy summary | Four large stat blocks is heavy for two runs. Keep **Total** and **Shadow pass rate**; fold Graded/Cancelled into a small caption underneath |
| Search placeholder | "Search SQL or table…" → "Search migrations…" |

Full SQL remains one click deeper on the run detail page — nothing is lost, it
is just no longer shouted at you from a table cell.

---

## 7. First / last name required

Those fields are rendered by **Clerk's hosted sign-up component**, and the
"Optional" tags come from your Clerk instance settings. Nothing in this repo
controls them. See **Task 3**.

---

## 8. Dashboard cleanup

**File:** `apps/web/app/dashboard/page.tsx`

- **Remove the "Recent" block** — lines **259–277**, the panel listing three
  runs under a `Recent` label.
- **Keep "Recent Activity"** (line 281). It is a different panel — a timeline of
  what happened, not a SQL list — and you asked specifically for "Recent runs".
  Leaving it alone.
- **Stop showing raw SQL** — `SqlBlock` renders `sqlSnippet` at lines **236**
  and **270**. Replace with a plain-English summary line, e.g.
  **"Add column · demo_items · Aug 8"**.

---

## 9. Sign-in email

Sender name, subject, body and styling are all generated by **Clerk**, not by
this app. It says "migrate ai" because that is your Clerk application's name.
See **Tasks 4 and 5**.

---

## 10. Model chatter under the prediction progress bar

**File:** `current-migration-workspace.tsx:2143-2151`

The bar renders `{progress?.message || "Working…"}` — text supplied by the
backend (`prediction_pipeline_service.py`), which is where the model-ish wording
originates.

**Plan:** keep the bar and the percentage; replace the message line with a
single fixed, human label — **"Analyzing your migration…"**. The exact rendered
string gets confirmed on screen before the edit, so the message line is removed
and not the progress bar with it.

---

# ✅ WHAT YOU NEED TO DO

Five things — all of them in GitHub's or Clerk's website, because they are
account settings that no amount of code in this repo can change. Everything else
on this page is mine.

These all take effect **immediately on the live site**, with no redeploy.

---

### TASK 1 — Make your GitHub App public (this fixes the 404)

> **Corrected 2026-08-15.** An earlier version of this file said to look for
> *"Where can this GitHub App be installed?"* at the bottom of the **General**
> page. That wording only appears on the **creation** form. For an app that
> already exists, the control lives on the **Advanced** tab. Use the steps
> below.

1. Go to **https://github.com/settings/apps**
2. Click **Edit** next to **Migration Oracle**.
3. In the **left sidebar** of the app's settings, click **Advanced**.
   *(The sidebar reads: General · Permissions & events · Install App ·
   Advanced · Optional features.)*
4. Scroll to the **"Danger zone"** box at the bottom.
5. Click the **Make public** button.
6. Confirm if GitHub asks.
7. Check it worked: open
   **https://github.com/apps/migration-oracle** in a private browser window.
   It should show a real page with an **Install** button instead of a 404.

*Note: once public it can only be made private again if no other account has
installed it.*

---

### TASK 2 — Check the two GitHub URLs ✅ DONE — verified 2026-08-15

Confirmed correct on all three sides (your GitHub App page, local `.env`, and
the **live deployed service**):

| | Value |
|---|---|
| App ID | `4514993` — matches everywhere |
| Client ID | `Iv23liQqujW04eOgDO6u` — matches everywhere |
| Callback URL | `…cs.amazonlightsail.com/api/github/oauth/callback` — matches |
| Webhook URL | `…cs.amazonlightsail.com/webhooks/github` — matches |
| Webhook secret, private key, state secret, token encryption key | all present in the deployment |

**Nothing more to do here.**

Minor, harmless note: your local `.env` still holds the old ngrok callback
(`https://tipping-outshoot-unloving.ngrok-free.dev/…`). It does **not** affect
production — `infra/lightsail/deploy.py` computes this value from the live API
URL and overwrites it on every deploy. Cleaning it up is cosmetic only.

---

### TASK 3 — Make first and last name required

> **Can this be done in code instead?** Partly. I checked the Clerk Backend API
> with your secret key: `GET /v1/instance` returns only
> `id / object / environment_type / allowed_origins / workspace_id`, and the
> user-attribute settings are not exposed on any Backend API endpoint. So it
> cannot be scripted.
>
> There *is* a code route: `components/signup-form.tsx` currently uses Clerk's
> prebuilt `<SignUp>` component, which renders whatever the instance settings
> say. Replacing it with a custom form built on `useSignUp()` would put the
> name fields fully under our control. That means rebuilding the OAuth buttons,
> the email-code verification step and the error states by hand — a real piece
> of work, not a touch-up, and a new place for sign-up bugs to hide days before
> a deadline. **Recommendation: use the dashboard toggle below.** Say the word
> if you would rather I build the custom form.

1. Go to **https://dashboard.clerk.com** and sign in.
2. Select your application (currently named **migrate ai**).
3. In the left sidebar, open **Configure**. Look for **Email, phone, username**
   — on some accounts this section is called **User & authentication**.
4. Find the **Name** row (it may sit under a heading like *Personal
   information* or *User model*).
5. Turn **Name** **on**, then set it to **Required** rather than *Optional*.
6. Save.
7. Check it worked: open your sign-up page in a private browser window. The
   grey "Optional" labels next to First name and Last name should be gone.

---

### TASK 4 — Rename the app so emails stop saying "migrate ai"

1. In **https://dashboard.clerk.com**, same application.
2. Go to **Settings** (the application settings page).
3. Change the **Application name** from `migrate ai` to **`Migration Oracle`**.
4. Save.

This one change fixes the email sender name, the subject line, the heading, and
the "© migrate ai" footer all at once.

---

### TASK 5 — Make the emails match the app

1. In **https://dashboard.clerk.com**, go to **Settings → Branding**.
2. Upload the logo. The file is already in your repo:
   ```
   frontend/oracle/apps/web/app/migration-oracle-logo.png
   ```
3. Set the accent / primary colour to the app's deep red: **`#8B1A1A`**
   (if that is not exactly right, use the colour of the "Set as current
   migration" button).
4. Save.
5. To edit the wording itself: left sidebar → **Customization** → **Emails**,
   then click the template card you want (the sign-in one is
   *"New device sign-in"*).

**About the `[Development]` prefix in the subject line:** that appears because
you are on Clerk development keys. Removing it needs a Clerk *production*
instance, which requires owning a domain. **Not worth doing before the
deadline** — leave it.

---

## After your tasks

Items 1, 2A, 2B, 3A, 3B, 5, 6, 8 and 10 are frontend-only and land as
**uncommitted changes**, so the deployed site is unaffected until you say so.

Item **4A** (invited members seeing runs) is backend, so it additionally needs a
Lightsail redeploy of the API to go live — no SAM build, since it does not touch
the Lambda code.

---

## Sources for the external steps

- [Making a GitHub App public or private](https://docs.github.com/en/enterprise-server@3.20/apps/creating-github-apps/registering-a-github-app/making-a-github-app-public-or-private) — "Only on this account" vs "Any account"; only public apps get an install landing page
- [Modifying a GitHub App registration](https://docs.github.com/en/apps/maintaining-github-apps/modifying-a-github-app-registration) — where Webhook URL and Callback URL live
- [Clerk: sign-up & sign-in options](https://clerk.com/docs/guides/configure/auth-strategies/sign-up-sign-in-options) — the name field lives in the user model settings
- [Clerk: email & SMS templates](https://clerk.com/docs/guides/customizing-clerk/email-sms-templates) — templates are under **Customization** in the side nav
- [Clerk: manage your workspace](https://clerk.com/docs/guides/dashboard/overview) — application name and Branding/logo live on the Settings page
