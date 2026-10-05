"""Authenticated ping to the Render scheduler; no local scheduling authority."""
import os
import httpx

if __name__ == '__main__':
    response=httpx.post(os.environ['OPENLEARN_REMINDER_API_ORIGIN'].rstrip('/')+'/internal/reminders/tick',headers={'X-OpenLearn-Cron-Secret':os.environ['OPENLEARN_CRON_SECRET']},timeout=50,trust_env=False)
    response.raise_for_status()
    print('Reminder tick completed.')
