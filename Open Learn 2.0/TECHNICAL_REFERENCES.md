# Technical references

References below are preserved from section 29 of the source document. They were not independently revalidated while organizing these briefs. Verify platform behavior against the selected support matrix during implementation.

The baseline architecture is described in the supplied OpenLearn review named Pasted text 20261001 013816. Its observations define the refactor starting point. The policies, schemas, interfaces, and thresholds in this brief are implementation decisions to validate through the repository and evaluation work.

The following official references support the specific platform constraints used in this design. Engineering should pin implementation dependencies and verify platform behavior against the chosen support matrix.

1. MDN MediaRecorder dataavailable event. Documents variable chunk timing and browser or platform interruption behavior. https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder/dataavailable_event

2. W3C MediaStream Recording specification. Establishes that individual recorder blobs need not be independently playable. https://www.w3.org/TR/mediastream-recording/

3. Chrome for Developers Native messaging. Documents native host registration, allowed extension origins, extension communication, and sender validation. https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging

4. Chrome for Developers Declare permissions. Documents extension and host permissions. https://developer.chrome.com/docs/extensions/develop/concepts/declare-permissions

5. Instructure Canvas Assignments documentation. Describes assignment dates, overrides, and student-facing assignment information. https://developerdocs.instructure.com/services/canvas/resources/assignments

6. PostgreSQL SELECT documentation. Describes row-locking clauses including SKIP LOCKED for appropriate work-queue use. https://www.postgresql.org/docs/current/sql-select.html

7. PostgreSQL Row Security Policies documentation. Describes database row security and its authorization role. https://www.postgresql.org/docs/current/ddl-rowsecurity.html
