# Mailroom Postman API Collection

Import `APIcollection.json` into Postman Desktop using **Import**. Start the Mailroom API, Redis, and the Celery worker before sending email requests.

## Collection variables and URL

The collection uses these variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `baseUrl` | `http://localhost:8000` | Mailroom API root. Change the host or port here if your API runs elsewhere. |
| `apiKey` | `dev-key-change-me-0123456789` | Sent as the `X-API-Key` header on every request except Health. Must match a key in the server's `API_KEYS`. |
| `deadLetterId` | empty | Filled by **List dead letters**; used by **Replay dead letter**. |
| `jobId` | empty | Filled automatically from the `data.id` returned by **Queue email**. |
| `idempotencyKey` | `mailroom-demo-1` | Identifies a create request. Keep the same value to test duplicate submission; change it to queue a new email. |
| `status` | `sent` | Optional job-list filter. Supported values are `queued`, `sending`, `sent`, `retrying`, and `dead`. |

All request URLs use `{{baseUrl}}`. The requests included are:

| Request | Method and URL | Purpose |
| --- | --- | --- |
| Health | `GET {{baseUrl}}/health` | Checks database and Redis connectivity. |
| Queue email | `POST {{baseUrl}}/emails` | Creates a job and queues the email; expects HTTP `202`. |
| Get email job | `GET {{baseUrl}}/emails/{{jobId}}` | Checks the job status. Run **Queue email** first. |
| Queue scheduled email | `POST {{baseUrl}}/emails` | Same as Queue email with `sendAt` (include a timezone offset). |
| List dead letters | `GET {{baseUrl}}/dead-letters?replayed=false` | Emails that failed permanently. |
| Replay dead letter | `POST {{baseUrl}}/dead-letters/{{deadLetterId}}/replay` | Re-queues one; a second call returns `409`. |
| List email jobs | `GET {{baseUrl}}/emails?page=1&pageSize=20&status={{status}}` | Lists jobs filtered by status. Remove the `status` query parameter to list all jobs. |

## Authentication

The collection sends the `X-API-Key` header (collection variable `apiKey`) on every request except **Health**. A missing or wrong key returns `401`. The `Idempotency-Key` header is separate: it only prevents duplicate sends and is **not** a credential.

## Queue email body

The request body is raw JSON with `Content-Type: application/json`:

```json
{
  "toEmail": "test@example.com",
  "subject": "Mailroom Postman test",
  "body": "Hello from the Mailroom Postman collection."
}
```

Fields:

| Field | Required | Requirements |
| --- | --- | --- |
| `toEmail` | Yes | A valid email address. |
| `subject` | Yes | 1–200 characters. |
| `body` | Yes | A non-empty string. |
| `sendAt` | No | Optional future date/time in ISO 8601 format, for example `2026-10-19T10:00:00Z`. Omit it to queue for immediate sending. |

Example with a scheduled send:

```json
{
  "toEmail": "test@example.com",
  "subject": "Scheduled message",
  "body": "This message is scheduled.",
  "sendAt": "2026-10-19T10:00:00Z"
}
```

## Idempotency header

**Queue email** sends this header:

```text
Idempotency-Key: {{idempotencyKey}}
```

Re-sending the request with the same key returns the existing job and does not enqueue another email. To create a fresh job, update the `idempotencyKey` collection variable before sending. The key may contain 1–100 characters. If omitted, each request can create a new job.

The collection automatically saves the response's `data.id` into `jobId` after a successful `202` response. Then send **Get email job** to poll status. A worker and reachable SMTP server (Mailpit for local testing) are needed for the job to reach `sent`.

## Response envelope

Successful endpoints return the standard response shape:

```json
{
  "statusCode": 202,
  "isSuccess": true,
  "data": {
    "id": "returned-job-uuid",
    "toEmail": "test@example.com",
    "subject": "Mailroom Postman test",
    "status": "queued",
    "attempts": 0,
    "lastError": null,
    "scheduledFor": null,
    "createdAt": "2026-10-18T12:00:00",
    "sentAt": null
  },
  "detail": "Email queued",
  "error": null
}
```

The worker updates the status asynchronously. It may briefly be `queued` or `sending` before becoming `sent`.
