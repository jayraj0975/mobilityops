# Pre-registration: holiday and long-weekend features

Written and committed **before** any forecast was evaluated on the months June to December 2024.
It fixes the hypothesis, the feature definitions, the evaluation and the decision rule so the
outcome cannot be shaped by what the test days happen to show. The result is reported in
[MODELING](MODELING.md) whether the features help or not.

## What was already known

On the January to May 2024 data the model scored a WAPE of 43.7% on federal-holiday hours against
17.8% overall ([report history](../reports/forecasting_real.md) at commit `b9d2f7e`). That is the
motivation, and it means January to May cannot be used as a fair test of a fix. No forecast,
error or holiday result on June to December has been looked at when this was written.

## Hypothesis

Demand on federal holidays and on the days around them differs in a way the current calendar
features (`is_holiday`, `is_day_before_holiday`, `is_day_after_holiday`) capture only crudely:
long weekends and the days between a holiday and a weekend behave like neither ordinary weekdays
nor ordinary weekends. Two extra calendar features will therefore reduce error on holiday days
without hurting other days.

## Features (fixed definitions, no tuning)

Both describe the target day and are known in advance, like the existing calendar features.

1. `is_long_weekend`: 1 if the day is a Saturday, Sunday, Friday or Monday that belongs to a run of
   three or more consecutive non-working days (weekend plus adjoining federal holiday), else 0.
   Federal holidays are those of `USFederalHolidayCalendar`, as elsewhere in the project.
2. `days_to_holiday`: signed number of days to the nearest federal holiday (negative before,
   positive after), clipped to the range -3 to +3; 0 on the holiday itself; +4 as a fixed
   "no holiday within three days" value.

No other feature, no hyper-parameter change, no change to the LightGBM settings, the folds or the
interval calibration. No annual-calendar features (day of year, Christmas distance): they would be
fitted to one December.

## Evaluation

* **Data:** yellow-taxi pickups per zone-hour, January to December 2024, cleaned exactly as before.
* **Primary test:** the default walk-forward configuration for this much history (4 folds of 14
  days, the last 56 days of the year, so about 5 November to 31 December), which contains
  Veterans Day, Thanksgiving and Christmas. Two models are run with identical settings, `base`
  (current features) and `holiday` (current features plus the two above).
* **Metrics:** pooled WAPE, WAPE on federal-holiday hours, WAPE on the days adjoining a holiday,
  and the day-level bootstrap interval of WAPE(base) minus WAPE(holiday) (positive = the new
  features are better), computed the same way as the existing bootstrap.
* **Secondary check** (only if the primary is inconclusive or the change of test period makes it
  worth it): the same comparison with the test folds ending on 30 September 2024, which contains
  Independence Day and Labor Day. It is reported next to the primary result and cannot overrule it.

## Decision rule

The features are **adopted** only if all of these hold on the primary test:

1. pooled WAPE improves (`base` minus `holiday` is positive) and its 95% bootstrap interval
   excludes zero;
2. WAPE on federal-holiday hours does not get worse;
3. no calendar slice reported in the existing tables (weekday, weekend, holiday, volume band)
   worsens by more than one WAPE point.

Otherwise they are **not adopted**, the shipped model stays as it is, and the report says so.
Whichever way it goes, the numbers are published.

## Known weakness of this test

There are only three federal holidays in the primary test window, so the holiday-hour estimate
rests on three days and its interval will be wide. That is stated in the report and is the reason
condition 1 is on pooled WAPE rather than on holiday hours alone.
