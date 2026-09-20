import subprocess
import sys

def run():
    # Read secrets directly from running API settings
    get_secrets_cmd = [
        "docker", "exec", "pbnc_api", "python", "-c",
        "from app.core.config import settings; import json; print(json.dumps({'SECRET_KEY': settings.SECRET_KEY, 'POSTGRES_PASSWORD': settings.POSTGRES_PASSWORD, 'DATABASE_URL': settings.DATABASE_URL, 'SYNC_DATABASE_URL': settings.SYNC_DATABASE_URL}))"
    ]
    raw_secrets = subprocess.check_output(get_secrets_cmd, text=True).strip()
    import json
    secrets = json.loads(raw_secrets)

    print("=== DYNAMIC SECRETS AUDIT AGAINST RUNNING CONTAINER LOGS ===")
    print(f"Loaded Real SECRETS from container runtime:")
    print(f"  SECRET_KEY length:       {len(secrets['SECRET_KEY'])} chars")
    print(f"  POSTGRES_PASSWORD:       [PROTECTED: {len(secrets['POSTGRES_PASSWORD'])} chars]")
    print(f"  DATABASE_URL server/db:  {secrets['DATABASE_URL'].split('@')[-1]}")
    print()

    targets = {
        "SECRET_KEY": secrets["SECRET_KEY"],
        "POSTGRES_PASSWORD": secrets["POSTGRES_PASSWORD"],
        "DATABASE_URL_PASSWORD": "postgres_password",
    }

    containers = ["pbnc_api", "pbnc_worker"]
    all_clean = True

    for container in containers:
        print(f"--- Auditing Container Logs: {container} ---")
        logs = subprocess.check_output(["docker", "logs", container], stderr=subprocess.STDOUT, text=True)
        log_lines = len(logs.splitlines())
        print(f"Audited {log_lines} lines of logs from {container}")
        
        for secret_name, secret_val in targets.items():
            if not secret_val:
                continue
            count = logs.count(secret_val)
            if count > 0:
                print(f"[FAIL] CRITICAL: Secret {secret_name} found {count} time(s) in {container} logs!")
                all_clean = False
            else:
                print(f"[PASS] Secret {secret_name}: 0 occurrences found")
        print()

    if all_clean:
        print("ALL RUNNING CONTAINER LOGS CONFIRMED CLEAN OF REAL RUNTIME SECRETS!")
    else:
        sys.exit(1)

if __name__ == "__main__":
    run()
