"""Create a private Render account configuration without printing passwords."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
from review_auth import hash_password


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', required=True)
    parser.add_argument('--clinics', required=True, help='Comma-separated actual clinic IDs. No wildcard.')
    parser.add_argument('--output', type=Path, default=Path('private_data/render-review-accounts.json'))
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', args.username):
        raise SystemExit('Use letters, digits, dots, underscores or hyphens in the username.')
    clinics = [c.strip() for c in args.clinics.split(',')]
    if not clinics or any(not re.fullmatch(r'\d+', c) for c in clinics):
        raise SystemExit('Supply actual numeric clinic IDs, separated by commas.')
    password = getpass.getpass('Reviewer password (at least 16 characters): ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords do not match.')
    output = args.output
    accounts = json.loads(output.read_text()) if output.exists() else {}
    if args.username in accounts:
        raise SystemExit('That reviewer already exists. Choose another username or intentionally edit the private account configuration.')
    accounts[args.username] = {'password_hash': hash_password(password), 'clinic_ids': list(dict.fromkeys(clinics))}
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(accounts, f, separators=(',', ':')); f.write('\n')
    output.chmod(0o600)
    print(f'Private account configuration saved to {output}. Paste its JSON into the Render REVIEW_ACCOUNTS_JSON secret. Do not commit it.')


if __name__ == '__main__':
    main()
