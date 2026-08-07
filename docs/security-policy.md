# Application Security Rules & Best Practices

This document outlines essential security guidelines, coding practices, and architectural principles required to protect applications and infrastructure against common vulnerabilities.

---

## 1. Authentication & Session Management

* **Enforce Strong Password Policies:** Require adequate password length, complexity, and check against known breached passwords (e.g., Have I Been Pwned API). Store passwords using strong, slow hashing algorithms like **Argon2id** or **bcrypt** with a unique per-user salt. Never use raw MD5, SHA1, or plain SHA256.
* **Implement Multi-Factor Authentication (MFA):** Support time-based one-time passwords (TOTP) or FIDO2/WebAuthn hardware keys for critical user accounts and administrative panels.
* **Secure Session Handling:**
  * Use cryptographically secure random number generators for session tokens.
  * Store session cookies with `HttpOnly`, `Secure`, and `SameSite=Strict` or `Lax` flags set.
  * Enforce strict session timeouts (both idle timeout and absolute session lifetime).
  * Invalidate sessions completely on logout and password reset.

---

## 2. Authorization & Access Control

* **Principle of Least Privilege:** Users, background jobs, and API integration tokens should only have access to the exact resources and permissions required to perform their tasks.
* **Enforce Denial by Default:** Explicitly deny access to all routes, files, and resources unless permission is explicitly granted.
* **Prevent Broken Object Level Authorization (BOLA / IDOR):** Never rely solely on sequential IDs (e.g., `/api/orders/123`). Always check if the authenticated user has explicit ownership or permission to access the requested resource ID on every request.
* **Role-Based Access Control (RBAC):** Centralize access control checks in a dedicated authorization layer or middleware rather than scattering permission checks throughout application code.

---

## 3. Data Validation & Output Encoding

* **Never Trust User Input:** Treat all incoming data—including query strings, form fields, headers, cookies, and file uploads—as untrusted.
* **Input Validation (Whitelisting over Blacklisting):** Validate input against strict schemas checking type, length, range, and format before processing.
* **Prevent SQL Injection:** Always use parameterized queries or Prepared Statements (or an ORM) when interacting with databases. Never concatenate strings to build raw SQL queries.
* **Prevent Cross-Site Scripting (XSS):** Contextually encode/escape output rendered in templates or HTML. Use modern web frameworks that perform automatic encoding by default.
* **Implement Content Security Policy (CSP):** Set HTTP `Content-Security-Policy` headers to restrict sources from which scripts, styles, and external resources can be loaded and executed.

---

## 4. Secrets Management & Environment Security

* **Never Commit Secrets:** Do not hardcode API keys, passwords, private SSH keys, or database credentials in source code.
* **Use Environment Variables & Secret Vaults:** Store secrets in environment variables (`.env`) for local development (excluded via `.gitignore`) and use secret management services (e.g., HashiCorp Vault, AWS Secrets Manager, GitHub Secrets) for production deployments.
* **Scan for Secret Leakage:** Set up automated pre-commit hooks and CI/CD secret scanning tools (e.g., `git-secrets`, Trufflehog, Gitleaks) to detect leaked tokens before pushing code.

---

## 5. Network, API & System Defense

* **Enforce TLS/HTTPS Everywhere:** Secure all communications with HTTPS using strong TLS configurations (TLS 1.2+). Redirect HTTP traffic automatically to HTTPS and enforce HSTS (`Strict-Transport-Security`).
* **Implement Rate Limiting & Throttling:** Protect authentication endpoints, APIs, and resource-heavy routes against brute-force, credential stuffing, and Denial of Service (DoS) attacks.
* **Prevent Cross-Site Request Forgery (CSRF):** Use Anti-CSRF tokens for state-changing requests (POST, PUT, DELETE) or rely on `SameSite=Strict`/`Lax` cookies with custom request headers (`X-Requested-With`).
* **Secure File Uploads:**
  * Validate file extensions against a strict whitelist.
  * Verify MIME types and inspect file headers (magic bytes).
  * Rename uploaded files to random UUIDs and store them outside the web root or on cloud object storage (e.g., S3).
  * Never allow execution of uploaded files (`.php`, `.sh`, `.exe`).

---

## 6. Logging, Auditing & Dependency Management

* **Audit Third-Party Dependencies:** Continuously scan open-source dependencies and packages for known vulnerabilities using automated tools (e.g., `npm audit`, `cargo audit`, Snyk, Dependabot). Update vulnerable packages promptly.
* **Log Security Events:** Log critical security events including failed login attempts, privilege escalation actions, access control failures, and input validation breaches.
* **Protect Log Integrity:** Include timestamps, request IDs, and user identifiers in logs, but **never log sensitive data** (e.g., raw passwords, payment card numbers, PII, session tokens). Keep logs centralized and restricted.

---

## 7. Hardening Architecture & Infrastructure

* **Disable Unnecessary Features:** Remove unused endpoints, default admin accounts, debugging pages, and unnecessary database services/ports from production servers.
* **Use Security Headers:** Set essential security response headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`).
* **Container & Environment Security:** Run application containers as non-root users, keep base container images minimal and updated, and isolate services using network policies and firewalls.