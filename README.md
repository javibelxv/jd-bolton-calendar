# JD Gyms Bolton → iCloud calendar

Every 6 hours, GitHub runs `jd_bolton_ics.py`, which reads the 7-day class
timetable on https://www.jdgyms.co.uk/gym/bolton/ and publishes it as a calendar
feed. Your iCloud calendar subscribes to that feed and refreshes on its own.

- New days appear as they're added to the timetable (it shows 7 days ahead).
- Cancelled or moved classes disappear from the feed.
- The last 4 weeks of classes stay visible as history.
- Classes are marked as "free" time, so they don't block your schedule.

## Subscribe

Feed URL: `https://javibelxv.github.io/jd-bolton-calendar/jd-bolton-classes.ics`

- **Mac (syncs to iPhone via iCloud):** Calendar → File → New Calendar
  Subscription → paste the URL → *Location: iCloud*, *Auto-refresh: Every hour* → OK.
- **iPhone only:** open https://javibelxv.github.io/jd-bolton-calendar/ in Safari
  and tap *Subscribe in Calendar*.

## Manual refresh

Actions tab → *Update JD Bolton class calendar* → *Run workflow*. Open the run to
see the list of classes it found.

## If something breaks

If JD change their website layout, the script stops without touching the feed
and the run fails — GitHub emails you. GitHub also pauses scheduled runs if a
repo has no activity for 60 days; the timetable updates normally keep it
active, but if you get a "scheduled workflow disabled" email, re-enable it in
the Actions tab.

## Another JD gym

Set `GYM_URL` and `GYM_NAME` in the workflow's run step, e.g.
`GYM_URL=https://www.jdgyms.co.uk/gym/bury/ GYM_NAME="JD Gyms Bury" python jd_bolton_ics.py`.
