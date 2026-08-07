# Install GitLab Runner ON the Wayhost VPS (no SSH deploy from CI)
#
# On the VPS (as root or with sudo), once:
#
#   curl -L https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh | sudo bash
#   sudo apt-get install gitlab-runner
#   sudo usermod -aG docker gitlab-runner
#   sudo gitlab-runner register --url https://gitlab.itnet-technologies.fr \
#     --token <PROJECT_OR_GROUP_RUNNER_TOKEN> \
#     --executor shell \
#     --description "wayhost-kvm1" \
#     --tag-list "wayhost-kvm1" \
#     --non-interactive
#   sudo systemctl enable --now gitlab-runner
#
# Then in GitLab → project → Settings → CI/CD → Runners:
#   - runner online, tag wayhost-kvm1
#   - "Run untagged jobs" can stay OFF (deploy jobs are tagged)
#
# Mac runners keep doing test/security; only deploy_wayhost requires wayhost-kvm1.
#
# Ensure /opt/app and /opt/src are writable by gitlab-runner (or use sudoers carefully):
#   sudo mkdir -p /opt/app /opt/src
#   sudo chown -R gitlab-runner:gitlab-runner /opt/app /opt/src
#   # OR keep ownership as emmy and add gitlab-runner to group emmy with write bits
