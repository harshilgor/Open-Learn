"""Install reviewed class speech defaults without displaying any credentials.

Prices reviewed 2026-10-13 against https://www.assemblyai.com/pricing.
Paid-route admission remains controlled by the existing usage policy.
"""
import argparse
import secrets
from backend.app.provider_key_routes import _read_values, _write_values, env_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--enable', action='store_true', help='Enable verification and live relay for new sessions after restarting the backend.')
    args = parser.parse_args()
    current = _read_values(env_path())
    values = {'OPENLEARN_CLASS_VERIFICATION_MODEL': 'universal-3-5-pro',
              'OPENLEARN_CLASS_STREAMING_MODEL': 'universal-3-6-pro',
              'OPENLEARN_ASSEMBLYAI_STT_USD_PER_MINUTE': '0.0035',
              'OPENLEARN_ASSEMBLYAI_KEYTERMS_USD_PER_MINUTE': '0.000833334',
              'OPENLEARN_ASSEMBLYAI_DIARIZATION_USD_PER_MINUTE': '0.000333334',
              'OPENLEARN_ASSEMBLYAI_STREAMING_USD_PER_MINUTE': '0.0075',
              'OPENLEARN_CLASS_STREAM_SECRET': current.get('OPENLEARN_CLASS_STREAM_SECRET') or secrets.token_urlsafe(48)}
    if args.enable:
        values.update(OPENLEARN_CLASS_VERIFICATION_ENABLED='true', OPENLEARN_CLASS_STREAMING_ENABLED='true')
    _write_values(values)
    print('Class speech defaults saved. Credentials were not displayed. Restart the backend to apply them.')


if __name__ == '__main__':
    main()
