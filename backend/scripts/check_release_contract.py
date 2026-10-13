"""Offline migration inventory gate. No database or provider calls."""
import json
from backend.app.release import code_schema_heads, release_contract


def main():
    contract = release_contract()
    if sorted(contract['schemaHeads']) != code_schema_heads():
        raise SystemExit('Update the release contract and review schema compatibility before release.')
    if contract['migrationOwner'] != 'single-release-job' or contract['migrationPolicy'] != 'expand-contract':
        raise SystemExit('Release migration ownership/policy is invalid.')
    print(json.dumps({'schemaHeads': contract['schemaHeads'], 'contract': 'valid'}))


if __name__ == '__main__':
    main()
