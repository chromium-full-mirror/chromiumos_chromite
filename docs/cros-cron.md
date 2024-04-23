# `cros cron`

`cros cron` is an optional job you may enable on your system to speed up common
developer workflows.  As of today, it implements prefetching git objects and SDK
tarballs.

[TOC]

## Should I enable the job?

Most developers will find `cros cron` useful, but here's what you should
consider when enabling it:

*  `cros cron` will only be useful if you regularly work on ChromeOS, and
   temporarily disables itself if you don't sync your checkout during a two week
   window.  If you don't regularly develop ChromeOS, or sync less than every two
   weeks, you probably shouldn't enable it.
*  `cros cron` will download new SDK tarballs as they become available.  This is
   a ~5 GB tarball every ~12 hours, which works out to ~300 GB of data monthly.
   If you pay for your internet by the gigabyte, you probably shouldn't enable
   the job.
*  `cros cron` can be enabled on a per-checkout basis.  It's most useful on the
   `main`, `snapshot`, and `stable` manifest branches, and likely not useful on
   release, firmware, and factory branches, as they simply don't see a lot of
   changes.

## Enabling the job

If your distribution uses systemd (most do these days), enabling `cros cron` is
very easy, just run:

```shellsession
(outside) $ cros cron enable
```

If your system doesn't use systemd, check your distribution's documentation on
how to create an hourly cron job, and setup a job which runs `cros cron run` as
your user account.

## Disabling the job

If you enabled the job with `cros cron enable`, you can disable it with
`cros cron disable`.

## Viewing job status

Running `cros cron status` will show you logs from the last run, as well as the
time until the next run.

## FAQs

### Can I add custom tasks into `cros cron`?

`cros cron` intentionally provides no hooks to add custom features to the job.
If you want to add custom features to the job, you should create your own cron
job (e.g., using a systemd timer).  You can integrate `cros cron` into your job
by calling `cros cron run` somewhere in your job.

### Where can I file bugs?

We have a
[template for you](https://issuetracker.google.com/new?component=1037860&template=1986113).
