Yes. I would define **OpenLearn 2.0** as the point where OpenLearn stops being primarily an AI tutor interface and becomes a **persistent learning intelligence system**.

The fundamental architecture is:

```text
                      OPENLEARN 2.0

             ┌─────────────────────────┐
             │   ACADEMIC WORLD MODEL  │
             │                         │
             │ courses                 │
             │ lectures                │
             │ assignments             │
             │ exams                   │
             │ syllabus                │
             │ professor emphasis      │
             │ deadlines               │
             │ concepts/prerequisites  │
             └────────────┬────────────┘
                          │
                  What must be learned?
                          │
                          ▼
              ┌───────────────────────┐
              │ LEARNING CONTROL PLANE│
              │                       │
              │ What should happen    │
              │ next for this student?│
              └───────────┬───────────┘
                          │
                 What should we do?
                          │
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
     TEACH              ASSESS              ACT
  Ask / Learn         Quiz / Review      Canvas/browser
       │                  │               Scheduling
       └──────────────────┼──────────────────┘
                          │
                          ▼
                Student interaction
                          │
                          ▼
                  EVIDENCE LEDGER
                          │
                          ▼
             ┌─────────────────────────┐
             │   LEARNER WORLD MODEL   │
             │                         │
             │ knowledge               │
             │ misconceptions          │
             │ uncertainty             │
             │ retention               │
             │ prerequisites           │
             │ preferences             │
             │ history                 │
             └─────────────────────────┘
```

Everything we have discussed fits into that architecture.

And importantly, **you do not need to throw away the current OpenLearn**. You already have courses, topic graphs, conversations, quizzes, assessment evidence, review memory, recordings, notes, and persistent database state. :chatgpt-content-reference{index="0"} The current backend is also already a modular monolith, which is a good architecture to evolve rather than replace. :chatgpt-content-reference{index="1"}

---

# 1. The foundation: Evidence Ledger

This is probably the first thing I would implement because almost everything else depends on it.

Today OpenLearn records quiz attempts, hints, retries, skips, scores, feedback and assessment evidence. :chatgpt-content-reference{index="2"}

OpenLearn 2.0 should generalize this into one universal event format.

Instead of different systems independently storing:

```text
quiz attempt
lesson completed
lecture recorded
hint requested
Canvas exam discovered
review completed
```

everything produces a `LearningEvent`.

For example:

```json
{
  "event_id": "...",
  "learner_id": "...",
  "course_id": "...",

  "event_type": "assessment_response",

  "concepts": [
    {
      "concept_id": "eigenvectors",
      "relevance": 0.92
    }
  ],

  "observation": {
    "correct": false,
    "score": 0.35,
    "independent": true,
    "hints_used": 0,
    "response_time_ms": 82000
  },

  "source": {
    "type": "quiz",
    "id": "quiz_123",
    "question_id": "q_4"
  },

  "timestamp": "...",

  "provenance": {
    "grader_version": "...",
    "model_version": "..."
  }
}
```

The event should describe **what happened**, not permanently decide what it means.

That distinction is fundamental.

```text
Evidence:
Student failed eigenvector transfer question.

Interpretation:
Maybe weak conceptual understanding.
Maybe weak null-space skills.
Maybe careless arithmetic.
Maybe misunderstood question.
```

The raw evidence is permanent.

Interpretations can change.

That means five years from now, if you develop a dramatically better learner-model algorithm, you can replay the student's learning history through the new model.

### Storage

This belongs in PostgreSQL, not Markdown.

Something like:

```text
learning_events
assessment_observations
concept_evidence
event_concept_links
event_sources
```

This becomes OpenLearn's historical truth.

---

# 2. Learner World Model

The Evidence Ledger tells OpenLearn **what happened**.

The Learner World Model tries to determine:

> What does the student probably know right now?

Your current system already has a concept state and review memory, but the reducer is intentionally fairly simple and standard quiz evidence is currently conservative. :chatgpt-content-reference{index="3"}

OpenLearn 2.0 should replace a simple concept label with a richer belief state.

Instead of:

```text
Eigenvectors:
developing
```

you eventually want:

```text
Eigenvectors

Conceptual understanding
strong probability: 0.81

Procedural skill
strong probability: 0.62

Transfer ability
strong probability: 0.39

Retention estimate
moderate

Last independent success
September 27

Evidence confidence
0.71

Possible misconceptions
null-space procedure missing: 0.58
eigenvalue/eigenvector confusion: 0.21

Untested
geometric interpretation
diagonalization transfer
```

The important concept is:

```text
OpenLearn doesn't know the student's mind.

OpenLearn maintains beliefs about it.
```

So learner state should explicitly contain **uncertainty**.

---

# 3. Concept graph becomes much more important

You already have topic graphs and prerequisites. :chatgpt-content-reference{index="4"}

In 2.0, I would make the concept graph a central structure.

Example:

```text
Linear Algebra
│
├── Vectors
│
├── Matrix multiplication
│
├── Determinants
│
├── Linear independence
│
├── Eigenvalues
│      │
│      └── Eigenvectors
│              │
│              └── Diagonalization
│
└── Systems of equations
```

But edges shouldn't just mean:

```text
A prerequisite of B
```

They can represent:

```text
prerequisite
related
often confused with
application of
special case of
generalization of
```

Then a failure on diagonalization can cause OpenLearn to investigate eigenvectors rather than blindly reteaching diagonalization.

This is how the learner model becomes structurally intelligent.

---

# 4. Misconceptions become hypotheses, not facts

This is one of the most important differences from normal AI tutoring.

Suppose a student fails:

\[
(A-\lambda I)v=0
\]

A normal tutor might say:

> You don't understand eigenvectors.

OpenLearn should instead maintain competing explanations.

```text
H1
Doesn't understand eigenvector definition
12%

H2
Doesn't understand null spaces
43%

H3
Arithmetic mistake
17%

H4
Confuses eigenvalue and eigenvector
24%

H5
Misread the question
4%
```

Then OpenLearn asks a question specifically designed to distinguish H2 from H4.

After the response:

```text
H2 → 78%
H4 → 8%
```

Now teaching can target the actual problem.

This becomes your **diagnostic reasoning engine**.

---

# 5. Quiz 2.0 becomes an active assessment system

Your existing quiz generator is already fairly sophisticated: it creates questions, performs deterministic validation, then uses another model call to solve/check them before presenting them. :chatgpt-content-reference{index="5"}

Keep that.

But change **who decides what question should be generated**.

Today the flow is approximately:

```text
Topic
↓
concept selection
↓
generate question
↓
grade
```

2.0 becomes:

```text
Learner World Model
↓
What are we uncertain about?
↓
What skill matters most?
↓
What question would provide the most useful evidence?
↓
Question specification
↓
Existing question generator
↓
Existing checker
```

The quiz planner might output:

```json
{
  "target": "eigenvectors",

  "goal": "disambiguate procedural vs conceptual weakness",

  "reasoning_type": "error_diagnosis",

  "difficulty": 0.58,

  "constraints": {
    "independent": true,
    "no_hint_initially": true,
    "require_reasoning": true
  }
}
```

The generator then turns that specification into the actual question.

That separation is extremely important:

```text
Quiz Planner:
WHY and WHAT should we test?

Question Generator:
HOW should the question be written?
```

---

# 6. Every question eventually becomes calibrated

Today "easy", "medium", and "hard" are essentially model judgments.

Over time OpenLearn should learn actual question behavior.

Suppose 10,000 students answer similar questions.

OpenLearn can estimate:

```text
Question family:
Eigenvector null-space transfer

Difficulty:
0.72

Discrimination:
0.84

Strong students correct:
89%

Weak students correct:
24%

Common wrong method:
uses determinant instead of null space
```

That eventually lets OpenLearn build something closer to a modern adaptive testing system rather than arbitrary AI-generated quizzes.

Generated questions become measurable instruments.

---

# 7. Teacher 2.0 becomes a pedagogical decision system

Ask/Learn currently build context from conversation state, concept graphs, evidence, course goals, notes and materials. :chatgpt-content-reference{index="6"}

2.0 goes further.

Instead of simply sending the model:

> The student struggles with eigenvectors. Explain them.

OpenLearn first decides what **teaching intervention** makes sense.

For example:

```text
Give direct explanation

Ask learner to predict

Give conceptual analogy

Show worked example

Give partially completed example

Reveal minimal hint

Contrast misconception with correct reasoning

Return to prerequisite

Ask for self-explanation

Give retrieval question

Give transfer problem
```

So:

```text
Learner World Model
        ↓
Pedagogical Policy Engine
        ↓
"Use worked example + prediction"
        ↓
LLM
        ↓
actual natural-language lesson
```

The LLM becomes the **communication layer**, not the entire educational strategy.

---

# 8. OpenLearn learns which teaching methods work for the individual

This is one of the most powerful long-term opportunities.

Suppose across six months OpenLearn observes:

```text
For this learner:

Long verbal explanations
→ mediocre retention

Worked examples followed by independent practice
→ excellent retention

Hints too early
→ lower transfer performance

Visual geometric explanations
→ strong conceptual understanding
```

Then OpenLearn gradually learns:

\[
P(\text{learning gain} \mid
\text{student},
\text{concept},
\text{intervention})
\]

Now personalization means much more than:

> The student likes concise responses.

It becomes:

> This instructional strategy has historically produced better learning outcomes for this student.

That is dramatically more meaningful.

---

# 9. Memory becomes a full memory lifecycle

Your current memory already isn't simply Markdown. OpenLearn has conversation state, courses, notes, assessment evidence, concept state and review memory. :chatgpt-content-reference{index="7"}

2.0 should formalize six memory types.

| Memory | Purpose |
|---|---|
| Raw artifacts | Audio, PDFs, slides, transcripts |
| Evidence memory | What the learner actually did |
| Episodic memory | Important historical learning experiences |
| Semantic memory | Durable facts OpenLearn has consolidated |
| Learner-state memory | Current belief about knowledge |
| Procedural memory | How OpenLearn itself performs recurring tasks |

### Example

Raw transcript:

```text
Professor: "...and this WILL appear on Midterm 2."
```

Becomes an episode:

```text
Professor emphasized Gauss's law.
```

Then possibly becomes semantic memory:

```text
PHY9B Midterm 2 includes Gauss's law.
```

With provenance pointing back to:

```text
lecture_12
00:47:13–00:47:28
```

The raw transcript still exists.

Nothing gets magically invented.

---

# 10. Where Markdown fits

Markdown remains extremely useful.

But it is for human-readable artifacts:

```text
lecture notes
study guides
summaries
course pages
memory inspection
lesson documents
```

The canonical state lives in PostgreSQL.

Large files live in object storage.

You might use:

```text
PostgreSQL
    structured state

pgvector
    semantic retrieval

S3/R2/etc.
    audio
    PDFs
    images
    large artifacts

Markdown
    user-facing documents
```

So Markdown is a **view of memory**, not the database itself.

---

# 11. Context Compiler replaces ordinary RAG

Currently Ask/Learn and Quiz consume different context. Your existing architecture already identified that Quiz receives a narrower packet and does not automatically receive the same broader lecture-note retrieval as Ask/Learn. :chatgpt-content-reference{index="8"}

2.0 should fix that with a single Context Compiler.

For every model call:

```text
Task
+
Learner Model
+
Academic Model
+
available sources
+
token budget
       ↓
Context Compiler
```

Suppose the teacher needs to explain eigenvectors.

The compiler decides:

```text
Include:
current eigenvector state
relevant misconception
matrix multiplication prerequisite
previous failed problem
professor's notation
relevant lecture excerpt

Don't include:
unrelated course memories
entire conversation history
old irrelevant quizzes
```

For a quiz:

```text
Include:
uncertain concepts
recent independent evidence
exam scope
question families already used
known misconceptions

Exclude:
full tutoring conversation
irrelevant personal preferences
```

One memory system.

Different compiled views.

---

# 12. Recording 2.0 has two jobs

The first job is **never lose the lecture**.

Your existing system already records browser audio chunks into IndexedDB and later processes them. :chatgpt-content-reference{index="9"}

Strengthen that into:

```text
phone microphone
↓
5–15 second chunks
↓
IndexedDB/local durable queue
↓
upload
↓
server acknowledgement
↓
remove confirmed local chunk later
```

Meanwhile:

```text
audio stream
↓
live transcription
↓
partial transcript
```

Those are separate paths.

If transcription fails, the audio survives.

If internet disappears, chunks survive.

---

# 13. Recording's bigger job: understand the lecture

The transformative part isn't transcription.

It's turning the lecture into changes in the Academic World Model.

Example:

```text
Lecture 12

10:02
Review of electric fields

10:17
New concept:
Electric flux

10:24
New equation:
Φ = ∫ E·dA

10:41
Professor emphasis:
"This is important for the exam."

10:49
Common mistake:
surface normal direction

11:02
Homework:
problems 7–13
```

Then OpenLearn updates:

```text
Course coverage

Concept graph

Professor emphasis

Possible exam scope

Referenced assignments

Relevant source material
```

Each statement keeps provenance back to the exact audio/transcript.

---

# 14. This produces the Academic World Model

The Academic World Model represents:

```text
What courses exist?

What concepts does each course contain?

What has actually been taught?

What is coming next?

What assignments exist?

What exams exist?

What did the professor emphasize?

What material is likely relevant?

What sources support those facts?
```

Sources include:

```text
Canvas
syllabus
recorded lectures
uploaded slides
assignments
course documents
student notes
```

The Academic World Model should never assume:

```text
Professor taught X
=
student knows X
```

Those are separate worlds.

---

# 15. Canvas becomes a computer-use system

Because you cannot depend on Canvas API access, OpenLearn needs browser execution.

Architecturally:

```text
Study Agent
    ↓
BrowserRuntime interface
       /        \
      /          \
Local Browser   Cloud Browser
```

The Study Agent might request:

```text
get_courses()

get_upcoming_assignments()

find_exam_dates()

read_course_modules()

read_syllabus()
```

The runtime underneath can accomplish that by clicking and reading Canvas.

The agent doesn't need to know whether the browser lives locally or in the cloud.

---

# 16. Start with local browser control

Initially:

```text
OpenLearn desktop application
↓
student's existing browser
↓
Canvas
```

Benefits:

```text
student already logged in

no password storage

no cloud browser cost

easier security boundary
```

OpenLearn extracts structured information:

```text
course
assignment
deadline
exam
announcement
module
```

and sends that to the backend.

You do not need a full VM for this.

---

# 17. Add cloud browser execution later

Local execution has one obvious limitation:

```text
Laptop off
=
agent unavailable
```

For features such as:

> Check Canvas every morning.

or:

> Remind me whenever the professor changes an exam date.

you eventually need cloud execution.

Then:

```text
OpenLearn
↓
isolated persistent cloud browser
↓
Canvas
```

The browser can maintain the user's authenticated session.

Only if OpenLearn later needs:

```text
terminal

arbitrary applications

filesystem

desktop software
```

would I move toward full per-user VMs/microVMs.

Canvas itself does not justify that complexity initially.

---

# 18. The Canvas agent should learn reusable skills

Do not make an expensive LLM reason through:

> How do I navigate Canvas?

every single time.

The first successful workflow might be:

```text
Open Canvas
↓
Courses
↓
EEC100
↓
Assignments
↓
extract assignments
```

Store that as procedural memory:

```text
canvas.get_assignments
```

Next time OpenLearn executes the skill.

If it fails because Canvas changed:

```text
fallback to browser reasoning
↓
repair procedure
↓
save new procedure
```

So the browser system gets faster and more reliable over time.

---

# 19. Security becomes a first-class subsystem

A browser agent reading arbitrary web pages cannot be allowed unrestricted authority.

Create an enforcement layer outside the LLM.

Example:

| Action | Policy |
|---|---|
| Read assignment | Automatic |
| Read syllabus | Automatic |
| Read grade | Automatic |
| Download PDF | Usually automatic |
| Send Canvas message | Confirmation |
| Submit assignment | Confirmation |
| Change account settings | Block/confirmation |
| Drop course | Block |

Web content is always considered untrusted.

The website cannot grant itself new agent permissions.

---

# 20. Study Planner becomes a closed-loop controller

Most study apps create:

```text
Monday:
Chapter 3

Tuesday:
Chapter 4
```

OpenLearn 2.0 should continually replan.

Suppose the student has two hours.

OpenLearn calculates:

```text
Upcoming exams

Importance of concepts

Current mastery

Retention decay

Prerequisites

Available time

Expected benefit of each activity
```

It might produce:

```text
25 min
Eigenvector diagnostic

40 min
Diagonalization lesson

15 min
Gauss law recall

30 min
Homework

10 min
Review errors
```

But then the first diagnostic reveals that eigenvectors are actually strong.

The system immediately changes the plan.

```text
25 minutes freed
↓
reallocate to diagonalization
```

The schedule is therefore dynamic rather than fixed.

---

# 21. Readiness Engine

When the student asks:

> Am I ready for my midterm?

OpenLearn combines:

```text
Academic World Model
↓
What appears to be on the exam?

Learner World Model
↓
What does the learner know?

Evidence Ledger
↓
How strong is our evidence?
```

The result shouldn't simply be:

```text
82% ready
```

Instead:

```text
Strong evidence:
matrix multiplication
determinants

Developing:
eigenvalues

Weak:
eigenvectors

No independent evidence:
diagonalization

Stale evidence:
row reduction

Highest uncertainty:
applications
```

Then:

> The most useful next step is a short diagnostic on diagonalization.

OpenLearn distinguishes:

```text
you don't know this

from

I don't yet know whether you know this.
```

That distinction is enormously valuable.

---

# 22. Ask, Learn and Quiz remain product modes

I would keep your existing interface.

```text
Ask

Learn

Quiz
```

Your existing system already treats these as workflows. :chatgpt-content-reference{index="10"}

Don't turn them into completely separate autonomous agents.

Instead:

```text
Ask Mode
↓
Learning Control Plane
↓
answer / explanation / retrieve

Learn Mode
↓
Learning Control Plane
↓
structured teaching intervention

Quiz Mode
↓
Learning Control Plane
↓
active assessment
```

The memory and intelligence underneath are shared.

---

# 23. Use the word "agent" selectively

Internally I'd use:

```text
Study Agent
```

for the Canvas/browser agent because it genuinely performs multi-step autonomous actions.

Possibly:

```text
Assessment Planner
Pedagogical Planner
```

rather than Quiz Agent and Teacher Agent.

Ask/Learn/Quiz themselves remain workflows.

This gives you cleaner engineering.

```text
Workflow state
≠
Agent state
≠
Learner state
```

---

# 24. The Learning Control Plane is the heart of 2.0

Eventually almost every meaningful interaction begins here.

Imagine the student says:

> Teach me diagonalization.

The Control Plane asks:

```text
What is the goal?

What prerequisites matter?

What does the learner probably know?

What are we uncertain about?

What previous evidence exists?

What is the best pedagogical action?
```

Maybe OpenLearn discovers:

```text
Eigenvectors weak
```

Instead of blindly explaining diagonalization, it might say:

> Before we start, solve this quick eigenvector problem.

One minute later it has evidence.

Then it decides whether to:

```text
continue

repair prerequisite

teach normally

skip material already mastered
```

That's the difference between chat personalization and an actual learning system.

---

# 25. Evaluation infrastructure is mandatory

This part is easy to overlook and may ultimately determine whether OpenLearn works.

Every intervention needs measurable outcomes.

You should eventually track:

| Horizon | Question |
|---|---|
| Immediate | Did they answer correctly afterward? |
| 1 day | Can they retrieve it? |
| 1 week | Did they retain it? |
| 1 month | Is it still retained? |
| Transfer | Can they use it in a different problem? |

Then compare interventions.

For example:

```text
Student A

Eigenvector misconceptions

Worked example:
7-day retention = high

Direct explanation:
7-day retention = moderate

Socratic hints:
transfer = highest
```

Eventually OpenLearn learns which strategy actually works.

That's what lets the system improve scientifically rather than merely changing prompts.

---

# 26. Infrastructure underneath all of this

I would continue with the modular monolith instead of microservices.

Conceptually:

```text
backend/app/

identity/
security/

evidence/
    events
    provenance

learner_model/
    state
    mastery
    retention
    misconceptions
    uncertainty

academic_model/
    courses
    concepts
    assessments
    curriculum
    lecture_coverage

memory/
    episodic
    semantic
    consolidation
    retrieval

context/
    compiler

pedagogy/
    policy
    interventions

assessment/
    planner
    generation
    validation
    grading

recording/
    capture
    chunks
    transcription
    lecture_analysis

browser/
    runtime
    local
    cloud
    skills
    policy

planning/
    schedules
    readiness
    replanning

evaluation/
    learning_gain
    retention
    experiments
```

They're modules.

Not separate servers.

That keeps development much easier.

---

# 27. Data architecture

At a high level:

```text
POSTGRESQL

users
courses
concepts
concept_edges

learning_events
assessment_attempts
concept_evidence

learner_concept_state
misconception_hypotheses
retention_state

academic_events
assessments
assignments
course_coverage

memories
memory_links

browser_accounts
browser_tasks
browser_skills

study_plans
study_plan_actions
```

Then:

```text
OBJECT STORAGE

audio
PDFs
slides
images
raw transcripts
recordings
```

And potentially:

```text
PGVECTOR

semantic memory
transcript retrieval
note retrieval
episode retrieval
```

You don't need a separate vector database initially.

---

# 28. Identity must be solved before persistent browser access

Your existing system still has some local-development assumptions around learner identity. :chatgpt-content-reference{index="11"}

Before 2.0 becomes hosted, finish:

```text
real accounts

authenticated sessions

multi-device syncing

encrypted secrets

browser-session ownership

authorization boundaries

audit logs

account deletion

data export

token/session revocation
```

This becomes especially important once OpenLearn can access university accounts.

---

# 29. What the full OpenLearn experience eventually feels like

Imagine September.

You install OpenLearn.

You say:

> Open Canvas and import this quarter.

OpenLearn discovers:

```text
EEC100
MAT22A
PHY9B
```

It finds:

```text
syllabi
assignments
calendar
exam dates
modules
```

This initializes the **Academic World Model**.

Then you attend PHY9B.

You tap:

```text
Record Class
```

The lecture ends.

OpenLearn now understands:

```text
what was taught

what the professor emphasized

what homework was mentioned

which concepts are new
```

That night:

> Teach me today's physics lecture.

OpenLearn compares:

```text
today's curriculum

against

your current learner state
```

It skips concepts you already clearly understand.

It notices a prerequisite weakness.

It teaches that first.

Then asks one diagnostic question.

You fail.

It develops two competing misconception hypotheses.

It asks another carefully selected question.

Now it knows which misconception is more likely.

It teaches specifically for that misconception.

A week later OpenLearn gives you a retrieval question because its retention model predicts that concept is becoming fragile.

Two weeks later:

> Am I ready for the midterm?

OpenLearn knows:

```text
what the exam likely covers

what the professor emphasized

what you've studied

what you've demonstrated

what you've forgotten

what remains uncertain
```

It creates a targeted diagnostic.

Your result updates your Learner World Model.

Your schedule for the next three days changes automatically.

That is OpenLearn 2.0.

---

# 30. How I would actually build it

I would not attempt all of this simultaneously. The implementation sequence matters because later systems depend on earlier primitives.

| Stage | Build | Why first |
|---|---|---|
| **2.0 Foundation** | Identity, Evidence Ledger, unified concept IDs | Everything depends on trustworthy data |
| **Learner Intelligence** | Learner World Model, uncertainty, misconceptions, retention | Gives OpenLearn persistent understanding |
| **Unified Memory** | episodic/semantic memory + Context Compiler | Makes Ask/Learn/Quiz share one intelligence layer |
| **Adaptive Quiz** | diagnostic planner + question information value | Produces much better evidence |
| **Adaptive Teaching** | pedagogical policy engine | Turns learner state into personalized instruction |
| **Recording 2.0** | resilient mobile capture + lecture understanding | Builds Academic World Model automatically |
| **Academic World Model** | coverage, exams, assignments, curriculum state | Gives OpenLearn external academic awareness |
| **Browser Agent** | local runtime, Canvas skills, security policy | Lets OpenLearn observe Canvas |
| **Cloud Execution** | persistent browser runtime | Enables scheduled/autonomous checks |
| **Planner + Readiness** | dynamic study planning and exam readiness | Combines both world models |
| **Learning Optimization** | long-horizon evaluation and intervention learning | Makes OpenLearn improve over time |

I would treat the first **five stages** as the intellectual core of OpenLearn 2.0.

Canvas/browser automation is exciting, but the real moat is not the ability to click Canvas.

The deeper moat is:

```text
Canvas tells OpenLearn
WHAT you need to learn.

Lectures tell OpenLearn
WHAT your professor taught.

Your interactions tell OpenLearn
WHAT you probably know.

The control system determines
WHAT should happen next.

And outcomes teach OpenLearn
HOW you personally learn best.
```

That is the full 2.0 thesis.

And if we build those primitives carefully, the long-term product is no longer simply competing with ChatGPT, Quizlet, NotebookLM, or generic note-taking apps. It becomes a persistent **learning operating system** whose internal model of the student and their academic environment gets richer every day they use it.