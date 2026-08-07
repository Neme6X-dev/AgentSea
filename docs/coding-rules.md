# Software Engineering Best Practices: Application Coding Rules

This document outlines the core engineering guidelines, design patterns, and standards required when building robust, scalable, and maintainable software applications.

---

## 1. Core Principles (The Foundation)

* **DRY (Don't Repeat Yourself):** Every piece of logic should exist in exactly one place. If you copy-paste code twice, refactor it into a shared function or module.
* **KISS (Keep It Simple, Stupid):** Avoid clever or overly complex code when a simple solution works. Readable code is always better than "smart" one-liners.
* **YAGNI (You Ain't Gonna Need It):** Don't write code or build abstractions for features you *might* need in the future. Build what is needed now.
* **Single Responsibility Principle (SRP):** Functions and classes should do **one thing well**. If a function requires "and" to explain what it does (e.g., `validateAndSaveUser`), split it into two.

---

## 2. Readability & Clean Code Rules

* **Name with Intent:**
  Variables, functions, and classes should state what they represent or do.
  * **Good:** `userAccountBalance`, `fetchActiveSubscriptions()`
  * **Bad:** `data`, `x`, `temp`, `handleStuff()`
* **Avoid Magic Numbers & Hardcoded Strings:** Use named constants instead of raw values scattered in logic.
  * **Bad:** `if (user.role === 3)`
  * **Good:** `if (user.role === ROLES.ADMIN)`
* **Keep Functions Short:** Ideally, limit functions to under 20–30 lines of code.
* **Comment the "Why", Not the "What":** Clean code should be self-explanatory. Write comments only to explain complex business logic, unusual design decisions, or workaround choices—not to describe obvious code.

---

## 3. Application Architecture & File Structure

* **Separation of Concerns:** Separate data models, business logic, API routes, and user interface elements. Never mix database queries directly into UI components or API controllers.
* **Consistent Directory Layout:** Group files logically by layer (e.g., `/controllers`, `/services`, `/models`) or by feature module (e.g., `/modules/auth`, `/modules/payments`).
* **Environment Configuration:** Never hardcode secrets, API keys, database URLs, or port numbers. Store them in environment variables (`.env` files) and keep secrets out of version control.

---

## 4. Error Handling & Security Rules

* **Fail Gracefully, Never Silently:** Always catch exceptions and return meaningful errors or fallback behavior. Avoid empty `catch` blocks.
* **Validate & Sanitize All Inputs:** Treat every external input (API payloads, query strings, user form inputs) as untrusted. Validate schemas before execution.
* **Prevent Common Vulnerabilities:**
  * Use parameterized queries/ORMs to prevent SQL injection.
  * Sanitize output rendered in the UI to prevent XSS (Cross-Site Scripting).
  * Enforce authentication and role-based access control (RBAC) on public endpoints.
* **Log Strategically:** Log system errors and critical events with structured data (timestamp, request ID, error stack trace), but **never log sensitive information** like passwords, credit card numbers, or API keys.

---

## 5. Testing & Maintenance Rules

* **Automate Testing:** Write unit tests for business logic, integration tests for APIs, and end-to-end tests for critical user journeys.
* **Enforce Formatting with Tooling:** Don't argue over tabs vs. spaces or semi-colons in code reviews. Use automated linters (e.g., ESLint, RuboCop, Pylint) and formatters (e.g., Prettier, Black) that automatically run on save or commit.
* **Use Version Control Correctly:**
  * Commit frequently with clear, descriptive commit messages.
  * Keep main branches protected and require pull requests (PRs) with peer code reviews before merging.
