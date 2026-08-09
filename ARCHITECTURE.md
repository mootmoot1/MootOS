# MootOS Architecture

## 1. Purpose

MootOS is a personal AI operating system designed to grow with Moot over time.

Its purpose is to provide one central AI that can:

- Talk naturally
- Understand ongoing conversation context
- Remember important information
- Organize projects and ideas
- Use tools
- Help build software
- Work from a phone or computer
- Run locally when possible
- Use cloud AI only when necessary
- Stay under the owner's control

MootOS is not limited to one category such as studio work, social media, vehicles, coding, finances, or scheduling.

Those are abilities that can be added to the same core system over time.

---

## 2. Core Design Principles

### Local-first

MootOS should run locally whenever the available hardware and software allow it.

Cloud models and outside services may be used when they provide a major benefit, but the system should not depend completely on one company.

### Replaceable models

The AI model should not be permanently tied to one provider.

MootOS should eventually support:

- Local open-weight models
- OpenAI models
- Other cloud AI providers
- Future models that do not exist yet

The model is the engine.

MootOS is the system built around the engine.

### User control

Moot stays in control of the system.

MootOS may:

- Suggest actions
- Draft content
- Write code
- Prepare changes
- Organize information
- Create plans

MootOS should require approval before it:

- Deletes important files
- Publishes content
- Sends messages
- Spends money
- Changes account settings
- Installs major updates
- Merges important code changes
- Gives outside services access to private information

### Modular growth

MootOS should be built in separate parts so new abilities can be added without rebuilding the entire system.

### Privacy

Personal information should remain local whenever possible.

Sensitive information should not be sent to outside AI services unless it is necessary and approved.

### Logged actions

Important actions and changes should be recorded so Moot can see what happened, when it happened, and why.

### Simple beginnings

The first version should use the simplest technology that can reliably accomplish the goal.

MootOS should not become unnecessarily complicated before the basic conversation and memory systems work.

---

## 3. High-Level System

MootOS will eventually contain the following major systems:

    MootOS
    |
    |-- Interface
    |-- Conversation Engine
    |-- Memory System
    |-- Model Router
    |-- Tool System
    |-- Coding Agent
    |-- Project System
    |-- Permission System
    |-- Logs
    |-- Storage
    |-- Settings
    |-- Security
    |-- Backup and Recovery
    |
    `-- Future Skills and Integrations

Each major system should remain as independent as reasonably possible.

This will allow parts of MootOS to be replaced, upgraded, or repaired without rebuilding the entire project.

---

## 4. Interface

The interface is how Moot communicates with MootOS.

The first interface should be a mobile-friendly website that works properly from a phone browser.

This is important because the first version may be created and tested mainly from a cell phone before Moot purchases a stronger computer.

Later interfaces may include:

- Desktop application
- Native mobile application
- Voice assistant
- Command-line interface
- Notifications
- Screen-sharing interface
- Wearable-device access
- Vehicle interface

The first interface should support:

- Text conversation
- Conversation history
- Starting a new conversation
- Continuing an old conversation
- Viewing saved memories
- Deleting or correcting memories
- Project selection
- File uploads
- Tool approvals
- Code-change approvals
- Settings
- Error messages
- Account login

The interface should feel like one continuous assistant rather than a collection of unrelated tools.

---

## 5. Conversation Engine

The conversation engine manages natural communication between Moot and MootOS.

Its responsibilities include:

- Understanding the current request
- Tracking the current subject
- Handling natural topic changes
- Remembering recent messages
- Resolving references such as "that project," "the other idea," or "what we discussed earlier"
- Recognizing when Moot is correcting previous information
- Asking questions only when necessary
- Deciding when to search memory
- Deciding when to use a tool
- Deciding when to send work to the coding agent
- Keeping responses understandable and useful
- Maintaining Moot's preferred communication style

The conversation engine should maintain short-term context from the current conversation.

Long-term information should be stored separately in the memory system.

The conversation engine should not treat every statement as permanent truth.

It should distinguish between:

- Temporary conversation details
- Possible ideas
- Confirmed facts
- Preferences
- Decisions
- Tasks
- Long-term memories
- Information that needs clarification

---

## 6. Memory System

The memory system is one of the most important parts of MootOS.

Its purpose is to help the AI understand Moot better over time without permanently storing every sentence or creating incorrect memories.

The memory system should support several different memory types.

### Personal memory

Long-term preferences, goals, routines, values, communication style, and important life information.

### Project memory

Information connected to a specific project.

Possible projects include:

- MootOS
- Studio work
- Social media content
- Vehicle repairs
- Business plans
- Financial goals
- Coding projects
- Personal development

### People memory

Information about clients, collaborators, family members, friends, contacts, and other important people.

### Conversation summaries

Compressed summaries of older conversations that preserve important context without saving every message in the active prompt.

### Decisions

Important choices, what was decided, when it was decided, and the reasoning behind the decision.

### Tasks and commitments

Things Moot plans to do, deadlines, promises, reminders, and follow-up actions.

### Preferences

How Moot likes things handled, written, organized, displayed, or explained.

### Temporary memory

Information that matters for a short period but should expire later.

### Corrections

Updated information that replaces an older incorrect memory.

The memory system should support:

- Saving
- Searching
- Retrieving
- Updating
- Correcting
- Deleting
- Reviewing
- Tagging
- Categorizing
- Connecting related memories
- Tracking when a memory was created
- Tracking where a memory came from
- Tracking whether a memory is confirmed or uncertain

Moot should be able to say things such as:

- "Remember this."
- "Do not remember that."
- "Forget that."
- "Update that information."
- "That is no longer true."
- "What did we decide before?"
- "What were we talking about last week?"
- "Show me what you remember about this project."
- "Why do you remember that?"
- "Delete everything connected to this subject."

Important memories should be reviewable by Moot.

MootOS should not silently store highly sensitive information unless the system is specifically configured and approved to do so.

---

## 7. Model Router

The model router chooses which AI engine should handle a request.

Possible AI engines may include:

- A small local conversation model
- A stronger local reasoning model
- A cloud model
- A coding-focused model
- A vision model
- A speech-to-text model
- A text-to-speech model
- An embedding model used for memory search

The router should consider:

- Task difficulty
- Cost
- Privacy
- Speed
- Available hardware
- Internet availability
- Whether the task contains sensitive information
- Which model is best suited for the task
- Whether Moot has approved cloud usage

Example routing:

    Simple conversation
    -> Local model

    Memory search
    -> Local model plus memory database

    Difficult reasoning task
    -> Stronger local model or approved cloud model

    Complex coding task
    -> Coding-focused model or coding agent

    Image analysis
    -> Vision-capable model

    Voice input
    -> Speech-to-text model

    Spoken response
    -> Text-to-speech model

    Current online research
    -> Web tool plus appropriate model

Moot should eventually be able to configure:

- Monthly cloud budget
- Daily usage limits
- Local-only mode
- Ask-before-cloud mode
- Preferred providers
- Preferred local models
- Tasks that are never allowed to use cloud services
- Automatic fallback rules
- Maximum allowed cost per request

The model router should record which model handled important requests and how much cloud usage cost.

---

## 8. Tool System

> **Implementation status (V0.2A):** a first, small version of this system
> is implemented and merged to `main`, live-verified on Railway/OpenAI —
> see `docs/TOOL_SYSTEM.md` for the concrete architecture and ADR-027 for
> the decision record. It registers exactly four internal tools
> (`projects.list`, `memory.search`, `tasks.list`, `tasks.create`) behind a
> fail-closed risk/permission model and a human-approval gate for writes.
> Everything else on this page remains the long-term vision for where the
> Tool System is headed, not a description of what is registered today.
>
> **Next phase (V0.3/V0.4, locked):** the permanent plan for how MootOS
> describes what it has, reasons about capability gaps, and — much later,
> human-approved at every step — builds new capabilities itself, is
> recorded in `docs/CAPABILITY_ARCHITECTURE.md` and ADR-028 through
> ADR-034. It keeps the Tool Registry below as the only executable source
> of truth and adds a Capability layer (a semantic grouping of tools,
> backed by them, never executing on its own) above it. **V0.3A is
> implemented and merged** — `ToolDefinition` now carries capability/
> side-effect/idempotency/limitation metadata, and the model-facing
> capability manifest is generated from the live registry instead of
> hand-maintained (`docs/TOOL_SYSTEM.md` §16, ADR-028/ADR-029). **V0.3B
> (structured gap reasoning) is implemented on branch
> `claude/v0.3b-structured-gap-reasoning`, pending merge** —
> `backend/gap_reasoning.py` turns a goal into a structured, audited Gap
> Report without executing anything (`docs/GAP_REASONING.md`, ADR-030).
> V0.3C onward remain plan only — see that document before extending
> further.

Tools give MootOS abilities beyond conversation.

A tool is a controlled function that the AI is allowed to use.

Future tools may include:

- Calculator
- Calendar
- File search
- File creation
- Web research
- GitHub
- Email
- Contacts
- Notes
- Content planner
- Social media publishing
- Audio transcription
- Image analysis
- Screen analysis
- Computer control
- Revenue tracking
- Client tracking
- Vehicle records
- Weather
- Reminders
- Database search
- Document creation
- Code execution
- Music and audio utilities

Every tool should clearly define:

- What it can read
- What it can create
- What it can change
- What it can delete
- Whether approval is required
- What information it sends outside the device
- What information it stores
- What actions are logged
- What happens when it fails

Tools should be added one at a time and tested separately.

Read-only access should generally be added before write access.

For example, MootOS may first be allowed to read a calendar before it is allowed to create or delete events.

---

## 9. Coding Agent

The coding agent is responsible for helping MootOS gain new abilities.

The coding agent may use Codex, GitHub Copilot, another coding model, or a future coding system.

Its responsibilities may include:

- Reading the MootOS repository
- Understanding feature requests
- Asking necessary technical questions
- Creating implementation plans
- Writing code
- Editing existing code
- Fixing bugs
- Running tests
- Creating tests
- Reviewing code
- Explaining changes
- Creating Git branches
- Preparing pull requests
- Checking compatibility
- Updating documentation
- Identifying security risks

The coding agent should not silently rewrite the live system.

The preferred workflow is:

    1. Moot requests a feature.
    2. MootOS clarifies the goal when necessary.
    3. The coding agent creates a written plan.
    4. The coding agent works in a separate branch.
    5. Automated tests are run.
    6. The changes are reviewed.
    7. Moot receives a clear explanation.
    8. Moot approves or rejects the change.
    9. Approved changes are merged.
    10. The update is recorded in the logs.

Future coding roles may include:

- Builder
- Debugger
- Test agent
- Security reviewer
- Performance reviewer
- Documentation writer
- Code reviewer

The coding agent should not receive unrestricted access to passwords, financial accounts, personal messages, or unrelated private files.

---

## 10. Project System

MootOS should organize work into projects.

Each project may contain:

- Name
- Description
- Goals
- Current status
- Conversations
- Memories
- Files
- Tasks
- Decisions
- Code repositories
- Deadlines
- People involved
- Activity history
- Notes
- Related tools
- Relevant permissions

Example projects may include:

- MootOS
- Studio business
- Social media content
- Mercedes project
- Personal finances
- Future business ideas
- Health and fitness
- Home repairs
- Music projects

Moot should be able to switch projects during a conversation without losing overall context.

MootOS should understand both project-specific context and broader personal context.

For example, a studio conversation may relate to income goals, scheduling, clients, social media, and future software features at the same time.

---

## 11. Permission System

Permissions control what MootOS can do automatically.

Suggested permission levels include:

### Read-only

The system may view information but cannot change anything.

### Suggest

The system may recommend or prepare an action but must wait for approval.

### One-time approved action

The system may complete one specific action after Moot approves it.

### Limited trusted automation

The system may perform a recurring action under clearly defined rules.

### Never allowed

Certain actions may be permanently blocked unless settings are manually changed.

High-risk actions should always require approval.

Examples include:

- Sending money
- Making purchases
- Posting publicly
- Deleting important files
- Sending messages
- Changing passwords
- Changing security settings
- Merging major code changes
- Installing unknown software
- Sharing private information
- Granting access to another person or service

Moot should be able to revoke permissions at any time.

Permissions should be specific instead of overly broad.

For example:

- "Read my calendar" is different from "edit my calendar."
- "Draft an Instagram caption" is different from "publish to Instagram."
- "Prepare a pull request" is different from "merge into the main branch."

---

## 12. Logs and Transparency

MootOS should maintain logs for important activity.

Logs may include:

- Tool calls
- Memory changes
- Code changes
- Model used
- Cloud cost
- Files accessed
- Files changed
- Actions approved
- Actions denied
- Errors
- Security warnings
- External services contacted
- Information sent outside the local device
- Software updates

Moot should be able to ask:

- "What did you change?"
- "Why did you do that?"
- "Which model handled that?"
- "How much did that cost?"
- "What information did you send to the cloud?"
- "Which files did you open?"
- "What did you remember from that conversation?"
- "Undo the last change."

Logs should be readable and understandable, not only technical system records.

---

## 13. Storage

Early versions should use simple and reliable storage.

Possible starting options include:

- SQLite database
- Local JSON files
- Markdown files
- Local folders

Later versions may add:

- Vector database
- Encrypted storage
- Automatic backups
- Cloud backups
- Multiple-device synchronization
- Media storage
- Version history
- Archived memories

SQLite is a strong starting option because it is lightweight, local, widely supported, and does not require a separate database server.

The first version should avoid unnecessary storage complexity.

---

## 14. Security

MootOS may eventually have access to personal conversations, files, accounts, projects, and private information.

Security must therefore be treated as a core system rather than an optional future feature.

Early security requirements should include:

- Password-protected access
- Secure handling of API keys
- API keys stored outside the main source code
- Private repository when appropriate
- Limited permissions
- Confirmation before high-risk actions
- Activity logs
- Protection against accidental deletion
- Input validation
- Safe error handling

Later security features may include:

- Encryption at rest
- Encrypted backups
- Multi-factor authentication
- Device approval
- Session expiration
- Role-based access
- Security audits
- Automatic dependency scanning

No password, secret key, account token, or private credential should be committed directly to GitHub.

A `.env` file may be used locally for secrets, and it should be excluded through `.gitignore`.

---

## 15. Backup and Recovery

MootOS should be designed so important memories and project information are not lost if a device fails.

The backup system should eventually support:

- Database backups
- Memory backups
- Project-file backups
- Configuration backups
- Encrypted backup copies
- Restore testing
- Version history

Moot should be able to restore the system after:

- Computer failure
- Accidental deletion
- Broken software update
- Database corruption
- Lost device
- Security incident

The live system and the backup system should not depend on only one physical device.

---

## 16. Version 0.1 Scope

Version 0.1 should prove that MootOS can function as a real conversational foundation.

Version 0.1 should include:

- Mobile-friendly chat interface
- Natural text conversation
- Short-term conversation context
- Basic long-term memory
- Ability to save important memories
- Ability to retrieve relevant memories
- Ability to review memories
- Ability to correct memories
- Ability to delete memories
- Replaceable model connection
- Basic activity logging
- Simple settings
- Clear separation between interface, memory, model, and storage
- Secure handling of API keys
- Basic user login or access protection

Version 0.1 does not need:

- Instagram publishing
- Full computer control
- Multiple autonomous agents
- Advanced voice mode
- Real-time screen vision
- Automatic self-updating
- Financial account access
- A large local model
- A native phone application
- Continuous background operation
- Fully automatic coding and deployment

Those features can be added later.

The main question Version 0.1 must answer is:

Can Moot have a natural ongoing conversation with MootOS, and can MootOS remember useful information well enough to make future conversations better?

---

## 17. Suggested Version Roadmap

### Version 0.1 — Conversation and Memory

- Chat interface
- Conversation context
- Long-term memory
- Memory controls
- Model connection
- Basic security
- Activity logs

### Version 0.2 — Projects

- Project creation
- Project-specific memory
- Tasks
- Files
- Decisions
- Project history

### Version 0.3 — Basic Tools

- Calculator
- File tools
- Calendar reading
- Web research
- Basic GitHub reading
- Document creation

### Version 0.4 — Coding Agent

- Repository access
- Feature planning
- Code generation
- Testing
- Pull requests
- Approval system
- Code-change logs

### Version 0.5 — Voice and Remote Access

- Speech-to-text
- Text-to-speech
- Secure remote access
- Mobile notifications
- Wake-word research

### Version 0.6 — Vision

- Image uploads
- Screenshot analysis
- Screen context
- Camera input
- Visual project understanding

### Version 0.7 — Automations

- Scheduled tasks
- Follow-up reminders
- Content workflows
- Business workflows
- Recurring reports
- Approval rules

### Version 0.8 — Personal Integrations

- Calendar editing
- Email tools
- Contacts
- Social media tools
- Client records
- Revenue tracking

### Version 0.9 — Local AI Expansion

- Local model support
- Local embeddings
- Local speech tools
- Cloud fallback
- Cost routing
- Privacy controls

### Version 1.0 — Personal AI Operating System

A stable system that can:

- Hold natural conversations
- Maintain useful long-term memory
- Organize projects
- Use approved tools
- Assist with building new software features
- Work from a phone
- Route between local and cloud models
- Protect personal data
- Explain important actions
- Remain under Moot's control

---

## 18. Initial Technology Direction

The exact technology may change, but an early build could use the following structure.

### Frontend

- Simple mobile-friendly web interface
- HTML, CSS, and JavaScript
- A lightweight frontend framework only if it becomes useful

### Backend

- Python
- FastAPI or a similar lightweight framework

### Database

- SQLite

### AI connection

- Cloud model during early development
- Local model support added later
- Model provider kept replaceable
- API access controlled through the model router

### Memory search

- Basic database search first
- Embeddings and semantic search added when needed

### Local model runner

- Ollama or another compatible local model system

### Repository

- GitHub

### Development assistant

- Codex
- GitHub Copilot
- Another coding agent
- Manual coding when necessary

### Hosting during early development

Possible early hosting options include:

- A free or low-cost cloud development environment
- GitHub Codespaces if available
- A lightweight web-hosting service
- A temporary cloud server
- A future home computer

The architecture should avoid permanently tying MootOS to one vendor or hosting provider.

---

## 19. Suggested Repository Structure

The repository may eventually use a structure similar to this:

    MootOS/
    |
    |-- README.md
    |-- ARCHITECTURE.md
    |-- ROADMAP.md
    |-- V0.1_REQUIREMENTS.md
    |-- LICENSE
    |-- .gitignore
    |
    |-- docs/
    |   |-- vision.md
    |   |-- decisions.md
    |   `-- security.md
    |
    |-- frontend/
    |   |-- static/
    |   |-- templates/
    |   `-- app files
    |
    |-- backend/
    |   |-- api/
    |   |-- conversation/
    |   |-- memory/
    |   |-- models/
    |   |-- tools/
    |   |-- permissions/
    |   `-- logs/
    |
    |-- database/
    |   |-- schema/
    |   `-- migrations/
    |
    |-- tests/
    |
    |-- scripts/
    |
    `-- config/

This structure is only a starting direction.

The coding agent may recommend changes as the project becomes more developed.

---

## 20. Long-Term Vision

MootOS should eventually become one central system that understands Moot's life, ideas, work, and projects.

The long-term experience should feel like this:

Moot speaks naturally.

MootOS understands the context.

It recalls relevant history.

It helps turn ideas into plans.

It uses tools when needed.

It sends coding work to the coding agent.

It asks for approval before important actions.

It becomes more capable over time without taking control away from Moot.

MootOS should grow through deliberate improvements, not uncontrolled self-modification.

The goal is not to create a system that can do everything immediately.

The goal is to create a strong foundation that can keep gaining useful abilities for years.

---

## 21. Definition of Success

MootOS is successful when it becomes genuinely useful in Moot's daily life.

Success does not require movie-level artificial intelligence.

Early success means:

- Moot can talk to it naturally from a phone.
- It understands the current conversation.
- It remembers selected important information.
- It can retrieve relevant past context.
- Moot can inspect and control its memory.
- The AI model can be replaced without rebuilding the entire system.
- New tools can be added without damaging the core.
- Important actions remain under Moot's control.

Long-term success means MootOS becomes the central system Moot uses to manage ideas, projects, information, tools, and future AI capabilities.
