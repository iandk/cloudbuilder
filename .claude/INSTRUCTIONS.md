# LLM Instructions for Cloudbuilder

> Mandatory instructions for any LLM working on this project.

---

## Documentation Update Requirements

**CRITICAL**: After making ANY changes to this project, you MUST update the relevant documentation:

### 1. CHANGELOG.md (`.claude/CHANGELOG.md`)

Update this file for EVERY change, no matter how small:

```markdown
## YYYY-MM-DD

### Category (e.g., "Templates.json Changes", "Bug Fixes", "New Features")

**Brief Title**

- What was changed
- Why it was changed (if not obvious)
- Which files/templates were affected
```

### 2. CLAUDE.md (Root directory)

Update if the change affects:

- Template structure or fields
- Distro-specific behaviors
- Build pipeline behavior
- Common patterns or solutions
- Testing requirements

### 3. README.md

Update if the change affects:

- User-facing behavior
- CLI options
- Configuration format
- Installation/usage instructions

---

## Before Making Changes

1. **Read the existing documentation** to understand current state
2. **Check CHANGELOG.md** for recent changes and context
3. **Understand the template structure** in CLAUDE.md

---

## Templates.json Editing Guidelines

### Adding a New Template

1. Use an existing similar template as a base
2. Match the package naming conventions for that distro family
3. Include ALL standard components:
   - Package upgrade command
   - QEMU guest agent cron
   - Sysctl hardening
   - MOTD setup (correct mechanism for distro)
   - SSH key regeneration
   - Cloud-init cleanup
   - Machine-id truncation

### Modifying Existing Templates

1. Consider if the change should apply to ALL templates
2. Use `replace_all: true` for changes that should be consistent
3. Verify JSON validity after changes: `python3 -m json.tool templates.json`

### Crontab Syntax Standard

Always use this pattern:

```bash
(crontab -l 2>/dev/null; echo '*/1 * * * * pgrep -f qemu-ga >/dev/null || systemctl start qemu-guest-agent') | crontab -
```

### Package Updates

- Set `update_packages: false`
- Add manual upgrade as FIRST command in `run_commands`:
  - DNF: `sudo dnf -y upgrade`
  - APT: `apt-get update && apt-get -y dist-upgrade`

### SSH Key Regeneration

Include near the end of `run_commands`, before cloud-init cleanup:

- RHEL/Fedora: `rm -f /etc/ssh/ssh_host_*` + `systemctl enable sshd-keygen.target` + `systemctl enable sshd`
- Debian/Ubuntu: `rm -f /etc/ssh/ssh_host_*` + `systemctl enable ssh`

---

## Testing After Changes

After modifying templates.json:

1. Validate JSON: `python3 -m json.tool templates.json > /dev/null && echo "Valid"`
2. If possible, build one template to verify
3. Check the testing checklist in CLAUDE.md

---

## File Locations

| File                      | Purpose                                                    |
| ------------------------- | ---------------------------------------------------------- |
| `CLAUDE.md`               | Main LLM context - template structure, patterns, solutions |
| `.claude/CHANGELOG.md`    | All changes with dates and details                         |
| `.claude/INSTRUCTIONS.md` | This file - LLM behavior requirements                      |
| `README.md`               | User documentation                                         |
| `templates.json`          | Template definitions                                       |
