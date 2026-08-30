# Sending as an M365 shared mailbox, through Microsoft Graph

How the laboratory sends mail. The application also has a generic SMTP backend
as a fallback for a deployment with no M365 tenant, but this is the path in
use -- run one or the other, since two means two sending identities for the
same laboratory and two external providers to evaluate under ISO/IEC
17025:2017 clause 6.6.

**Why Graph and not SMTP to Exchange Online.** A shared mailbox has no password
and no licence, so it cannot authenticate over SMTP at all. Authenticating as a
licensed user and sending as the shared mailbox is refused — `5.7.60 Client does
not have permissions to send as this sender` — because SMTP AUTH requires the
From to match the authenticating mailbox. Microsoft is also retiring SMTP AUTH
client submission in Exchange Online. **Check your Message Center for the state
of your tenant before assuming either way**; the direction of travel is not in
doubt, but the dates have moved before.

**What this buys over a third-party relay.** SPF, DKIM and DMARC are already in
place if your domain is in M365, so there is no DNS verification to do and no
sending domain to get approved — with most providers that approval is the item
that gates first send, and it is measured in working days. One external
provider instead of two. And Exchange keeps a message trace, which is better
delivery evidence under clause 7.5 than "the relay accepted it".

---

## 1. The shared mailbox

Exchange admin center → **Recipients → Mailboxes → Add a shared mailbox**.

Use an address that reads correctly in a customer's inbox — it is the From on
every notification the laboratory sends. `lims-notifications@<your-domain>` is
the shape; avoid `no-reply@`, since customers do reply to results notifications
and a black hole is a poor experience for a laboratory that wants to hear about
a wrong address.

Shared mailboxes are normally unlicensed. **Confirm the licensing position for
*programmatic* access with whoever manages your tenant** — Microsoft's terms
around applications accessing a shared mailbox have nuance that is not worth
guessing at, and getting it wrong is a licensing finding rather than a
technical failure.

## 2. A separate app registration

Entra admin center → **App registrations → New registration**. Name it for
what it does, e.g. `NexusLIMS Mail`.

**This must not be the SSO registration.** Two reasons, both operational:

- Rotating the mail secret must never be able to lock the laboratory out of
  signing in. Mail and login should fail independently.
- The SSO registration's permissions were consented for sign-in. Adding
  tenant-wide `Mail.Send` to it widens what a stolen SSO secret is worth.

No redirect URI, no platform — this app never signs a person in.

## 3. The permission, and narrowing it

**API permissions → Add a permission → Microsoft Graph → Application
permissions → `Mail.Send`.** Then **Grant admin consent**; without consent it
is listed but inert.

> `Mail.Send` as an *application* permission is tenant-wide. As granted, this
> app can send as **any mailbox in the tenant**, including the Laboratory
> Director's. Narrow it before you put the secret anywhere.

Narrow it by creating a mail-enabled security group containing only the
notifications mailbox, then scoping the app to that group in Exchange Online
PowerShell:

```powershell
New-ApplicationAccessPolicy `
  -AppId <the app registration's Application (client) ID> `
  -PolicyScopeGroupId lims-mail-senders@<your-domain> `
  -AccessRight RestrictAccess `
  -Description "NexusLIMS may send only as the notifications mailbox"
```

Then prove it took, in both directions:

```powershell
Test-ApplicationAccessPolicy -Identity lims-notifications@<your-domain> -AppId <client id>
Test-ApplicationAccessPolicy -Identity <a director's mailbox>          -AppId <client id>
```

The first must return `Granted` and the second `Denied`. A policy that only
grants is half-tested — the denial is the half that matters.

**Microsoft has been moving this to RBAC for Applications**, which scopes the
same thing through management-role assignments. Check which mechanism your
tenant expects; the principle is identical and only the cmdlets differ.

## 4. The client secret

**Certificates & secrets → New client secret.** Choose the shortest expiry your
rotation process can actually keep up with. Copy the **Value**, not the Secret
ID; it is shown once.

**Secrets expire, and mail stops when they do.** The application turns that into
HTTP 401, which `is_transient()` classes as permanent, so it becomes a
SystemFailure in the Staff Console rather than a silent gap — but a diary entry
two weeks before expiry is cheaper than finding out that way.

## 5. The application's environment

```bash
DJANGO_EMAIL_BACKEND=apps.notifications.graph.GraphEmailBackend
DJANGO_DEFAULT_FROM_EMAIL=NexusLIMS <lims-notifications@your-domain>
GRAPH_MAIL_CLIENT_ID=<the app registration's Application (client) ID>
GRAPH_MAIL_CLIENT_SECRET=<the secret Value from step 4>
GRAPH_MAIL_SENDER=lims-notifications@your-domain
```

`GRAPH_MAIL_TENANT_ID` is not in that list: it falls back to
`AZURE_AD_TENANT_ID`, because it is the same tenant. Set it only if that is
somehow untrue.

The address in `DJANGO_DEFAULT_FROM_EMAIL` must be `GRAPH_MAIL_SENDER` — a
display name in front of it is fine and is what customers should see.
`config/settings.py` refuses to start if they differ, because Graph rewrites
the From to the mailbox it is scoped to rather than refusing, so a mismatch
would arrive looking like it came from an address the application never chose.

None of the SMTP variables (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_*`) apply.

## 6. Prove it

```bash
python manage.py send_test_email you@example.com
```

Then look in the shared mailbox's **Sent Items** — `saveToSentItems` is on by
default, so a successful send leaves a copy there. That is the check worth
doing: the command reports what Graph accepted, and Sent Items shows what
Exchange actually sent.

---

## When it does not work

| Symptom | Almost always |
|---|---|
| HTTP 403 `ErrorAccessDenied` | The application access policy does not cover this mailbox, or `Mail.Send` was never admin-consented. Re-run `Test-ApplicationAccessPolicy`. |
| HTTP 401 `invalid_client` | The client secret expired, or the Secret **ID** was copied instead of the **Value**. |
| HTTP 404 | `GRAPH_MAIL_SENDER` is not a mailbox in this tenant — check for a typo, or a mailbox that was never actually created. |
| HTTP 429 | Throttling. Nothing to fix: these are transient, and the retry sweep picks them up. |
| Refuses to boot naming `DJANGO_DEFAULT_FROM_EMAIL` | The From and the mailbox differ. See step 5. |

## Limits, and what this does not do

- **Throttling.** Graph allows roughly 30 messages a minute and 10,000
  recipients a day per mailbox. Comfortable for a laboratory — the progress
  digests batch above `SAMPLE_PROGRESS_DIGEST_THRESHOLD` precisely so a busy
  day does not turn into a message per sample — but the retry sweep can burst
  after an outage, and a burst that hits 429 is retried rather than lost.
- **Attachments** go inline, up to 3 MB. Larger needs a draft plus an upload
  session, which is not implemented: the backend raises rather than sending a
  message without its attachment. Nothing in the notification path attaches
  anything today; reports are linked, not attached.
- **No bounce handling.** A message Graph accepts
  and Exchange later cannot deliver is recorded as sent. Bounces land in the
  shared mailbox, where a person has to read them.
- **Data residency.** Mail sits in whichever geography your M365 tenant was
  provisioned in — for a Philippine tenant, typically the Asia Pacific geo
  rather than the Philippines. That is the same open question as hosting, and
  the tenant already carries it for SSO; it is worth putting to the PAB
  assessor as one question rather than two.
