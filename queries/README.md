# Queries

## Standalone

Run these directly. Each is commented with what it scans.

| File | What it answers |
|---|---|
| [`examples/cancellation_lead_time.sql`](examples/cancellation_lead_time.sql) | How much of the advertised timetable is deleted before the day — cancellations made a week ahead never reach a passenger's screen. |
| [`examples/delay_by_segment.sql`](examples/delay_by_segment.sql) | Which stretches of track actually manufacture delay, and which quietly recover it because the timetable is padded. |

## The passenger-hours metric

The rest of the files build one number: **how much passenger time the network
lost**. They are fragments — [`_base_passenger_hours.sql`](_base_passenger_hours.sql)
holds the shared CTEs and each aggregation file picks up from `lost`.
`site/aggregate/aggregate.py` joins them:

```python
sql = load_sql("by_operator", date(2026, 5, 16))
```

| File | Grain |
|---|---|
| `national.sql` | one row: total, and the delay/cancellation split |
| `by_operator.sql` | per operator, with a per-journey rate |
| `by_station.sql` | per destination station |
| `by_reason.sql` | per Darwin reason code |
| `worst_service.sql` | the single costliest train |

### Why not just count cancellations

Every published rail statistic counts trains. Trains are not what is being
wasted. A four-minute delay to a packed commuter service destroys more human
time than a whole day of cancellations on a quiet branch line, and no
train-counting metric can see that.

So each delayed or cancelled leg is weighted by the people who actually travel
it, and the answer comes out in hours.

### How a passenger load is estimated

`odm_v1` gives annual journeys between each station pair. Divide by 365 for a
daily figure, then by the number of services offering that pair that day. If
40,000 people a year travel Reading to Paddington and 120 trains a day serve it,
each train carries roughly 0.9 of those journeys.

An estimate, not a headcount — see the caveats in [DATA.md](../DATA.md).

### How lost time is counted

| | |
|---|---|
| **Delayed leg** | passengers × minutes late on arrival |
| **Cancelled leg** | passengers × wait for the next service on that pair |

The cancellation rule charges displacement rather than a flat penalty. Losing
one of 120 Reading–Paddington trains costs each passenger a few minutes; losing
one of four trains to a rural station costs them the cap (two hours by default).

### What it produces

Real output for 2026-05-16, a Saturday:

```
passenger_hours        117,660
hours_delays            88,374   (75%)
hours_cancellations     29,286   (25%)
services                22,826
journeys_estimated   2,975,127
```

About 2.4 minutes lost per journey made. The per-operator view is where it gets
interesting — CrossCountry lost 157 hours per thousand journeys that day against
Thameslink's 34, a gap that ranking by raw hours completely hides.

### Two things to watch

**Pass-through points.** `locations`/`stops` include timing points where a train
does not stop. They are flagged cancelled when the service is, so leaving them
in inflates every cancellation figure. The base query drops them with
`stop.arr_sched IS NOT NULL OR stop.dep_sched IS NOT NULL`.

**Multi-TIPLOC stations.** 29 stations span several TIPLOCs — Clapham Junction
has five. Group by CRS and deduplicate, or you will count a service as calling
there more than once.
