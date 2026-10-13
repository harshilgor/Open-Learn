# Production chat connectivity repair

The October 10 screenshot reports missing CORS headers on usage, session snapshot, and recording requests. Render logs show repeated SQLAlchemy QueuePool timeouts with five shared connections.

Identity validation used `SELECT ... FOR UPDATE` on the same account for ordinary transactions, serializing concurrent requests and nested validation. Authentication also inserted/upserted and updated the account on every poll. The repair uses a PostgreSQL shared row lock: concurrent validations can proceed while account deletion still waits for in-flight transactions. Authentication writes only when an account is new or its verified email changes.

IdentityMiddleware handles database pool timeouts before response headers are sent with HTTP 503, Retry-After: 3, no-store, and a safe database_busy error. The existing outer CORS middleware adds the permitted origin header. A stream that already started is never sent a second HTTP response.

19 focused identity/capacity/revocation tests passed. Tests cover unchanged authentication making no writes, changed email updates, deleted account denial, PostgreSQL lock SQL, and CORS-safe pool failures in authentication and endpoint execution. PostgreSQL concurrency is assessed by SQL semantics and subsequent production checks; local tests use SQLite and mocked capacity failures.

Release commit: 5ff4801453407cbbd6aad7892a1b3bd6f1560eb1. Render deployment: dep-db5bp5nlk1mc739eja0g.

Production verification: Render reported Live at 22:32:30 UTC. `/ready` returned 200; an anonymous allowance request returned 401 with Access-Control-Allow-Origin matching the production website. The authenticated browser retried the user's failed “How are you” request; generation gen_52120308f1b7480fada10485210dff18 completed with a visible response. Render log query found no QueuePool errors in the checked post-deployment window. Existing failed attempts are preserved as history; the current response is successful.

After refresh the saved successful response reloaded, Buddy controls and dictation became available, and the prior transient service notices cleared. Initial refresh still briefly displayed temporary service notices before automatic recovery; the fix should not be interpreted as proof of unlimited backend capacity or elimination of every possible outage. Proof screenshot: work/chat-connectivity-repaired.png.
