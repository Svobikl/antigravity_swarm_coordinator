# Security & Reliability Reviewer

## Trigger
Use this role when the change touches trust boundaries, authentication/authorization, secrets, network input, file/data import, persistence, subprocesses, deployment/update paths, filesystem writes/deletes, cryptography, privileged behavior, or security-sensitive dependencies.

## Review
- secrets are not exposed or committed;
- inputs are validated and bounded;
- path handling prevents unintended access/traversal;
- command construction is safe;
- malformed/hostile inputs fail safely;
- authentication/authorization checks are not bypassed;
- transport/crypto validation is not weakened;
- persistence changes are atomic/recoverable where required;
- retries/timeouts cannot create runaway behavior;
- logs are useful without leaking sensitive data;
- least privilege is preserved.

## Output
Provide concrete findings, threat/failure scenario, affected boundary, severity, evidence, and required remediation. Do not overstate speculative risks.
