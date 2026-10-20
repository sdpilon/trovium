# Feature Specification: Server Deployment

**Feature Branch**: `002-server-deployment`

**Created**: 2026-10-19

**Status**: Draft

**Input**: User description: "As a trovium user, I want to install/deploy the tool to my server(s) in a simple way with minimal steps"

## Clarifications

### Session 2026-10-19

- Q: Should this deployment specification include unattended scheduling of pipeline runs? → A: No. User Story 4 is completely out of scope; the feature covers install, repeatable deployment, upgrade, and uninstall. Scheduling is removed from the spec.
- Q: Does this feature target multiple servers or a single media library installation? → A: A single media library/installation per deployment. Multi-server fleet management is out of scope; retain unattended installation, repeatability, configuration files, run reports, idempotency, and offline installation.

### Session 2026-10-20

- Q: What should `--purge` do when no deployment record exists but a configuration file does? → A: Remove the configured configuration file only; without `--purge`, the operation remains a no-op. Media and source paths are never touched.

## User Scenarios & Testing _(mandatory)_

### User Story 1 - Install on a clean server with one command (Priority: P1)

An operator has a fresh, supported server and a media library that is already
mounted and available. They run one documented command. The command prepares
anything the trovium tools need, installs every shipped pipeline step for that
user, creates a usable default configuration, verifies that the installed tools
actually run, and prints the active version, the configuration location, and
the next step. The operator does not clone the repository, install a language
runtime, or use elevated privileges.

**Why this priority**: This is the user's headline need. Every other
deployment capability depends on a trustworthy first install, and a single
command with a self-check is what makes the tool practical on a server.

**Independent Test**: On a clean supported server image, run the documented
install command once as an ordinary user, then run the deployment status
command and a representative pipeline command. Confirm both work, the
configuration exists, and no root-owned or system-wide files were created.

**Acceptance Scenarios**:

1. **Given** a clean supported server with outbound network access, **When**
   the operator runs the single documented install command, **Then** every
   shipped trovium pipeline step is available to that user, the post-install
   self-check passes, and the command reports the active version, the
   configuration location, and the next step.
2. **Given** the operator has no administrative privileges, **When** install
   runs, **Then** it completes without elevation and writes only to
   user-owned locations.
3. **Given** the server cannot satisfy a prerequisite that the installer
   cannot prepare, **When** install runs, **Then** it changes nothing, exits
   non-success, and names the unmet requirement and a remedy.
4. **Given** the installed command location is not searched by the user's
   shell, **When** install finishes, **Then** it reports the exact change the
   user must make, without silently editing shell startup files.
5. **Given** the operator runs the same install command a second time with no
   new version requested, **When** it finishes, **Then** it reports that the
   installation is already current and makes no changes.

---

### User Story 2 - Install unattended and repeatably (Priority: P2)

An operator wants to install trovium without sitting at a terminal and to get
the same result every time they run the command. They supply all choices
through arguments, environment variables, or a configuration file. Nothing
prompts, each run reports what it did, and a repeated run is a no-op. When the
host has no outbound network, the operator can point the same command at a
locally available release bundle.

**Why this priority**: Unattended, repeatable installation is what makes the
tool practical to run on a server and safe to re-run. It also keeps the same
settings applied across reinstallations on the one host, without relying on
memory or interactive answers.

**Independent Test**: On a clean server, run the fully specified command with no
terminal attached. Verify it reports the active version, configuration
location, and actions taken, and that a second run reports no changes. Repeat
with network access disabled and a local release bundle.

**Acceptance Scenarios**:

1. **Given** every required setting is supplied non-interactively, **When**
   install runs without an interactive terminal, **Then** it completes without
   prompting, exits successfully, reports the active version and configuration
   location, and emits a run report of the actions it took.
2. **Given** the same version and settings are already installed, **When** the
   identical command runs again, **Then** it makes no changes and reports the
   installation as current.
3. **Given** the operator requests a specific version, **When** install
   completes, **Then** exactly that version is active and reported; without a
   request, the latest stable version is installed.
4. **Given** the host has no outbound network access, **When** install is given
   a local release bundle, **Then** it installs and verifies that bundle the
   same way it verifies a downloaded one.
5. **Given** two install or upgrade operations overlap on one host, **When**
   they run concurrently, **Then** one proceeds and the other waits or exits
   with a clear message; the host never ends in a mixed-version state.
6. **Given** the release bundle fails its integrity check, **When** install
   runs, **Then** it refuses the bundle, changes nothing, and names the failed
   check.
7. **Given** a configuration file containing all required settings, **When**
   install runs non-interactively, **Then** it applies those settings without
   prompting and preserves the file for reuse.

---

### User Story 3 - Upgrade and remove without losing configuration or media (Priority: P3)

An operator upgrades by running the install command again, or chooses an
earlier version to roll back. Their configuration and credential references
survive. If the new version fails its post-install self-check, the previously
working version stays active. When the operator removes trovium, the installed
commands are gone, while configuration and all media remain by default; an
explicit purge removes configuration only.

**Why this priority**: A server tool is only simple to operate if its second
day is as safe as its first. Upgrade and removal must not put the media library
or working configuration at risk.

**Independent Test**: Install, customize the configuration, upgrade, and verify
the version changed while the configuration is intact. Then uninstall and
verify the commands are gone, the configuration and a sampled media library are
untouched, and a second uninstall succeeds as a no-op.

**Acceptance Scenarios**:

1. **Given** an older version is installed and the configuration has been
   customized, **When** the operator upgrades, **Then** the new version becomes
   active, the configuration is preserved, and the version change is reported.
2. **Given** a new version fails its post-install self-check, **When** the
   upgrade finishes, **Then** the previously working version remains active or
   is restored, and the failure is reported with a remedy.
3. **Given** an installed version, **When** uninstall runs, **Then** the
   commands created by trovium are removed and no unrelated service, file, or
   setting is changed.
4. **Given** uninstall runs without a purge request, **When** it finishes,
   **Then** the configuration remains; with a purge request, the configuration
   is removed. The media library and download locations are untouched in both
   cases.
5. **Given** no installation exists on the server, **When** uninstall runs,
   **Then** it exits successfully and reports that there was nothing to remove.
6. **Given** the server reboots after install or upgrade, **When** it comes
   back up, **Then** the installed commands remain available.

---

### Edge Cases

- What happens if install is interrupted after some files are written? A re-run
  converges to a complete installation or a clean refusal; an interrupted run
  is never reported as a successful installation.
- What happens if the requested version does not exist or cannot be obtained?
  Nothing is changed, the failure names the requested version and the reason,
  and the currently installed version, if any, remains active.
- What happens if an existing configuration is from an older or newer version?
  It is preserved and backed up before any migration; settings that cannot be
  migrated safely are reported rather than dropped, and install does not
  silently replace the file.
- What happens if the operator previously ran trovium from a development
  checkout? The deployment reports the separate installation and does not
  remove or modify the checkout.
- What happens if `uninstall --purge` runs with no deployment record but a
  config file exists? The configured config file is removed; media, source, and
  client data are untouched.
- What happens if the install location is not on the user's command path? The
  operator receives the exact corrective instruction; no shell profile is
  edited without explicit consent.
- What happens if a secret is supplied where it could be recorded? Secrets are
  accepted only from the environment or a protected file, never from a
  command-line argument, and are redacted everywhere.
- What happens if the server is shared by multiple users? Each user's
  installation is isolated; one user's install, upgrade, or removal does not
  change another user's commands, configuration, or recorded state.
- What happens if the release bundle is not the one the installer expected?
  Integrity verification fails closed before any executable is run.
- What happens if the media library is on a volume that is not mounted at
  install time? Install can complete without it, but any validation that needs
  it reports the missing path clearly, and no files are written to a fallback
  location.

## Requirements _(mandatory)_

### Functional Requirements

- **FR-001**: The deployment feature MUST provide one documented command that
  installs every shipped trovium pipeline step for the invoking user on a clean
  supported server, without requiring the operator to clone the repository or
  preinstall the project's language runtime or build toolchain.
- **FR-002**: The installer MUST prepare anything it needs that is not already
  present. When it cannot prepare a prerequisite, it MUST fail before making
  changes, exit non-success, and name the unmet requirement and a remedy.
- **FR-003**: The default installation MUST be user-scoped and MUST NOT require
  administrative privileges. It MUST write only to user-owned locations and
  MUST NOT modify system-wide configuration.
- **FR-004**: Installation, upgrade, and removal MUST be idempotent: repeating
  the same operation with the same inputs makes no changes and reports the
  current state. Concurrent operations on one server MUST be serialized or one
  MUST fail with a clear message; mixed-version states MUST NOT occur.
- **FR-005**: The installer MUST run a post-install self-check that executes
  each installed pipeline step in a non-destructive way. It MUST report the
  active version, configuration location, and next step, and MUST exit
  non-success if the self-check fails.
- **FR-006**: The installer MUST support a fully non-interactive mode in which
  every input is supplied by arguments, environment variables, or a
  configuration file. In that mode it MUST NOT prompt and MUST fail with a list
  of missing inputs rather than waiting for a terminal.
- **FR-007**: The deployment MUST default to the latest stable version and MUST
  allow the operator to request a specific version, including returning to an
  earlier version. It MUST report the active version and MUST install all
  pipeline steps as one coherent set so that mixed versions are not exposed.
- **FR-008**: The deployment MUST support installation from a locally available
  release bundle when the server has no outbound network access, using the same
  verification and self-check path as a downloaded installation.
- **FR-009**: Every release bundle MUST be integrity-verified before any of its
  content is executed. A bundle that fails verification MUST be refused with a
  named cause, and nothing on the server may change.
- **FR-010**: The installer MUST create or use one documented, user-owned
  configuration file. It MUST generate a documented default configuration, MUST
  NOT silently overwrite an existing configuration, MUST back up any
  configuration it migrates, MUST keep the file editable by the operator, and
  MUST accept that same file as an input for unattended installs.
- **FR-011**: Secrets MUST NOT be accepted as command-line arguments, written
  to logs, printed by status, or stored in the installation record. Secret
  input MUST come from the environment or a protected file, and any file
  containing secret material MUST be readable only by its owner.
- **FR-012**: Before changing anything, the installer MUST validate the target
  environment and supplied configuration, including supported platform and
  architecture, install permissions, configuration syntax, and any paths the
  operator supplied. Unsupported environments MUST be refused with a named
  cause rather than installed in a degraded state.
- **FR-013**: Upgrade MUST use the same command as install, preserve existing
  configuration, and switch the active version only after the new version
  passes its self-check. If the self-check fails, the previously working
  version MUST remain active or be restored.
- **FR-014**: Uninstall MUST remove every command the deployment created, MUST
  preserve configuration and all media by default, and MUST remove
  configuration only when an explicit purge is requested. Uninstall on a server
  with no installation MUST succeed as a no-op and MUST report that nothing was
  removed. When no deployment record exists but a configuration file does, an
  explicit purge removes that configuration file; without purge, the operation
  remains a no-op.
- **FR-016**: The deployment MUST provide a status view reporting, at minimum,
  the active version, configuration location, and last self-check result.
  Status MUST complete without changing installation state.
- **FR-017**: Every deployment failure MUST be visible, MUST exit non-success,
  MUST name the cause, and MUST suggest a remedy. No operation may report
  success for work it did not complete.
- **FR-018**: Installation, upgrade, uninstall, and status MUST NOT modify or
  delete any file in the media library, download locations, or client data.
  The installer's access to those locations is limited to read-only validation
  when the operator has supplied them.
- **FR-019**: Per-user installations on a shared server MUST be isolated: one
  user's deployment operations MUST NOT alter another user's commands,
  configuration, or recorded state.
- **FR-020**: The installer MUST report whether the installed command location
  is reachable from the user's command path. If it is not, the installer MUST
  state the exact remedy and MUST NOT edit shell startup files without explicit
  consent.
- **FR-021**: The deployment state MUST be recorded in one inspectable,
  user-owned location containing the active version, installation paths, and
  configuration location, and that record MUST be updated only by the
  deployment tooling.
- **FR-022**: Upgrading, downgrading, or reinstalling MUST preserve existing
  configuration values that remain valid, and MUST NOT partially apply a
  version whose self-check fails.
- **FR-023**: Every install, upgrade, uninstall, and status invocation MUST
  produce a run report listing the actions taken, their outcomes, the active
  version, and the configuration location. The report MUST be machine-readable,
  MUST be emitted to standard output, and MUST redact all secret values.

### Key Entities _(include if feature involves data)_

- **Deployment Record**: The per-user, per-installation state of trovium:
  active version, installation location, configuration location, last
  self-check result, and last deployment outcome. It is the source of truth for
  status, upgrade, and uninstall.
- **Deployment Configuration**: The operator-owned configuration file and the
  settings pipeline steps need, such as library root, source or client
  connection details, placement mode, and references to secrets. It survives
  upgrades and uninstall unless purged.
- **Deployment Run Report**: The machine-readable record of one deployment
  invocation: the operation, actions taken, their outcomes, the active version,
  the configuration location, and any redacted errors.
- **Release Bundle**: A versioned, integrity-verified set of everything needed
  to install one coherent trovium version on a supported platform.
- **Target Server**: The supported host and user account receiving a deployment,
  including its platform, architecture, available paths, and privilege level.

### Out of Scope

- Unattended scheduling, recurring runs, and run notifications. The operator
  invokes deployed commands on demand or through a scheduler they own and
  manage outside trovium.
- Provisioning or configuring the operating system, storage mounts, network,
  firewall, or the download client.
- Multi-server fleet deployment, central orchestration, a deployment dashboard,
  or replicating one installation across many servers. Each deployment targets
  one server and one media library.
- Container images, container orchestration, and platform-as-a-service
  deployment.
- Automated deployment on macOS or Windows, and system-wide multi-user
  installations.
- Secret-manager integration or automatic credential rotation; deployment
  consumes references and protected inputs only.
- Media library backups, migration, or repair.
- Automatic migration of configuration across incompatible schema changes
  beyond preserving a backup and reporting what cannot be migrated.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: On a clean supported server, an operator reaches a verified,
  working installation with one command in under 5 minutes, excluding time
  spent waiting on an unusually slow network.
- **SC-002**: At least 95% of first attempts succeed across a matrix of clean
  supported server environments; every unsuccessful attempt names a cause and
  a remedy before changing the server. The matrix includes at least five clean
  positive cases and at least two negative preflight cases; results are
  recorded with pass/fail counts and the cause of any failure.
- **SC-003**: Repeating an identical install or upgrade completes in under
  30 seconds, makes zero changes, and exits successfully.
- **SC-004**: An unattended installation with all required settings supplied
  completes with zero prompts and emits a run report listing every action and
  its outcome, with all secret values redacted.
- **SC-005**: Across all install, upgrade, downgrade, and uninstall test
  scenarios, zero media files are modified or deleted, verified by comparing a
  complete before-and-after inventory.
- **SC-006**: An installation interrupted at any of at least five tested points
  recovers on the next run in 100% of cases, with no interrupted run reported as
  successful.
- **SC-007**: Across the deployment test matrix, zero secret values appear in
  command output, status output, or logs, and 100% of files containing secrets
  are readable only by their owner.
- **SC-008**: Upgrade preserves 100% of valid existing configuration values, and
  a failed upgrade leaves a working previous version active in 100% of tested
  cases.
- **SC-009**: Uninstall removes 100% of the commands the deployment created,
  completes in under 2 minutes, and leaves configuration unless purge was
  requested.
- **SC-010**: An installation from a local release bundle succeeds in 100% of
  tests with outbound network access disabled.
- **SC-012**: The status command reports version, configuration, and last
  self-check result in under 5 seconds without changing installation state.

## Assumptions

- The target server runs Linux on x86_64 or arm64 with a POSIX shell. Common
  Linux distributions are supported; automated deployment on macOS, Windows,
  and container platforms is out of scope for this feature.
- Each installation targets one server and one media library. Setting up
  another person's library is a separate installation; managing multiple
  libraries, tenants, or servers from one installation is out of scope.
  Non-interactive mode supports unattended installs and repeatable re-runs on
  that host.
- The default installation is per-user and unprivileged. System-wide,
  multi-user installation is out of scope; an operator who needs it can use a
  dedicated service account instead.
- The installer is distributed with each release and can obtain the matching
  release bundle over the network, or use a locally supplied bundle when the
  network is unavailable.
- The latest stable version is the default. An explicit version selection
  enables reproducible deployments and rollback-by-reinstall.
- The operator already owns and mounts the media library and runs any download
  client; deployment does not provision or manage either. Supplied paths may be
  absent at install time, in which case install can succeed but validation
  reports the missing path.
- Configuration is created with usable defaults but without client credentials.
  Missing or invalid runtime credentials are reported by validation and status,
  not treated as an installation failure.
- Deployment does not schedule or supervise pipeline runs. Operators invoke the
  deployed commands on demand or through a scheduler they own; recurring
  execution, run monitoring, and notifications are out of scope.
- Run reports describe deployment actions. Pipeline steps keep their own run
  records; deployment does not replace or aggregate them.
- Secrets are supplied through environment variables or a protected file.
  Secret-manager integration and credential rotation are outside this feature.
- The existing developer workflow of syncing and running from a checkout is
  unaffected; a checkout is not treated as an installation to be upgraded or
  removed.
- Release bundles and their integrity metadata are produced and published by
  the project's release process. Deployment verifies integrity but does not
  define how releases are built.
