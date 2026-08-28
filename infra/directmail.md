# DirectMail sending-domain setup

The one task standing between NexusLIMS and actually sending email. Everything
in the application is done — `apps/notifications/` queues, sends, retries and
records; `config/settings.py` refuses to start half-configured;
`manage.py send_test_email` proves the transport. None of it delivers a
message until a sending domain is verified, and **verification is a DNS task
with a multi-day dependency in the middle of it.**

Start it before you need it.

## Start with the DKIM ticket, today

Three of the four DNS records can be added in minutes. The DKIM value cannot:
Alibaba requires you to **raise a support ticket to be issued a DKIM record
value, and quotes 1–3 working days** to provide it. State your email-sending
scenario in the application.

That ticket is the long pole. Everything else on this page takes an afternoon;
this takes until Alibaba replies. Raise it first and do the rest while you
wait.

## Choose the sending domain

Use a **subdomain** — `mail.<your-domain>` or `notifications.<your-domain>` —
rather than the root.

This is a recommendation rather than an Alibaba requirement, and the reason is
concrete: verification needs an **MX** record, and per DNS rules **MX and
CNAME cannot coexist on the same hostname**. If anything already points a
CNAME at your root (`@`) — and something usually does — you would have to
delete it to add the MX. A subdomain keeps DirectMail's records away from
whatever your root is already doing.

Whatever you choose becomes the domain part of `DJANGO_DEFAULT_FROM_EMAIL`,
so pick one you are happy for customers to see.

## The four records

DirectMail asks for **four**: two TXT, one MX, one CNAME. The console shows
the exact values for your domain once you add it under **Email Domains** —
they are generated per-domain, so they are not reproduced here.

| # | Type | Host | Value | Where it comes from |
|---|---|---|---|---|
| 1 | TXT | as shown in console | ownership token | Generated per domain. This is the "prove you control this domain" record |
| 2 | TXT | `@` (or the subdomain) | `v=spf1 include:spf1.dm.aliyun.com -all` | Fixed. Declares which servers may send as you |
| 3 | MX | as shown in console | as shown in console | Generated per domain |
| 4 | CNAME | `default._domainkey` when the sending domain is the root | the DKIM value **from your support ticket** | The one with the lead time |

**Do not skip SPF or DKIM even though verification might pass without them.**
They are what stops a customer's COA notification landing in spam, and a
report-ready email nobody sees is indistinguishable from a report that was
never issued.

## Then verify

1. Add the records at your DNS provider.
2. Wait. Alibaba says to try after **20 minutes**; effect is typically within
   **4 hours** and can take up to **48**, depending on your DNS provider's TTL.
3. DirectMail console → **Email Domains** → **Verify** against your domain.

Check propagation before clicking, so a failed verification means something:

```bash
dig +short TXT mail.<your-domain>          # ownership token and SPF
dig +short MX  mail.<your-domain>
dig +short CNAME default._domainkey.mail.<your-domain>
```

If `dig` returns nothing, the records have not propagated and clicking Verify
will simply fail. If it returns the old values, you are seeing a cached TTL —
wait it out rather than re-adding the records.

## After the domain verifies

1. Create a **sender address** under the verified domain in the DirectMail
   console. This is what `DJANGO_DEFAULT_FROM_EMAIL` must be.
2. Set that address's **SMTP password** in the console. It is not your Alibaba
   account password, and it is shown once.
3. Fill in the application's environment (see `backend/.env.example`):

```bash
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_DEFAULT_FROM_EMAIL=no-reply@mail.<your-domain>   # the sender address
EMAIL_HOST=smtpdm.aliyun.com                            # or the regional smtpdm-<region>.aliyun.com
EMAIL_PORT=465
EMAIL_HOST_USER=no-reply@mail.<your-domain>             # the sender address again
EMAIL_HOST_PASSWORD=<the SMTP password>
EMAIL_USE_SSL=true
EMAIL_USE_TLS=false
EMAIL_TIMEOUT=10
```

4. Prove it:

```bash
python manage.py send_test_email you@example.com
```

## Ports: 465, and why not 587

**DirectMail does not offer 587.** Its SMTP ports are **25, 80 and 465**, so
the `EMAIL_PORT=587` default in `config/settings.py` — correct for most
providers — will not connect here.

**Port 25 is disabled on Alibaba ECS instances**, which is where this
application is most likely to run. That leaves:

| Port | Encryption | Use it? |
|---|---|---|
| 465 | Implicit TLS — the handshake happens before any SMTP command | **Yes.** `EMAIL_USE_SSL=true`, `EMAIL_USE_TLS=false` |
| 80 | Plain, or STARTTLS | No. Plain sends customer information in the clear, and STARTTLS on a plain port can be stripped in transit |
| 25 | STARTTLS | Blocked outbound on ECS |

For a laboratory sending customer notifications, 465 is the only defensible
choice — ISO/IEC 17025:2017 4.2 makes the lab responsible for the customer's
information, and that responsibility does not stop at the edge of the VPC.

`config/settings.py` will refuse to start if you set `EMAIL_USE_TLS` and
`EMAIL_USE_SSL` together, which is the mistake this table exists to prevent.

## When it does not work

| Symptom | Almost always |
|---|---|
| Verification fails in the console | Records not propagated yet — check with `dig` before retrying, and check you added them to the subdomain, not the root |
| `SMTPAuthenticationError` | `EMAIL_HOST_USER` is not the sender address, or the SMTP password was regenerated |
| `SMTPSenderRefused` / 550 on send | `DJANGO_DEFAULT_FROM_EMAIL` is not a sender address under the verified domain |
| Connection times out | Port 25 on ECS, or 465 not open outbound from the app subnet |
| Delivered but in spam | SPF or DKIM missing — verification can pass without them |

The application classifies these for you: a `550` is abandoned immediately
rather than retried, an `SMTPAuthenticationError` likewise, and both become a
`SystemFailure` an operator can read. See the Notifications section of the
root README.

## What is verified here, and what is not

**From Alibaba's own documentation:** the four-record requirement, the SPF
value `spf1.dm.aliyun.com`, the `default._domainkey` DKIM host, the DKIM
support-ticket requirement and its 1–3 day turnaround, the MX/CNAME
coexistence rule, the 20-minute / 4-hour / 48-hour verification timings, and
the SMTP ports 25/80/465 with 25 disabled on ECS.

**Not verified against a live account.** Nothing on this page has been run
against a real Alibaba tenant — the same caveat `infra/README.md` carries for
the Terraform, and for the same reason. Treat the console as authoritative
where it disagrees, and correct this file when it does.

**Not automated.** There is no Terraform here for DirectMail. The provider may
expose a sending-domain resource that would emit these records as outputs, but
this environment cannot reach the Terraform registry, so writing it would mean
guessing resource and attribute names — which is exactly how the first version
of `infra/main.tf` acquired four `validate` errors. If that is wanted, it
should be written where `terraform init` can run.
