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
`aggregate/aggregate.py` joins them:

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

### The coverage guard

That divisor assumes the day's data contains every service offering a pair. Some
of the time it does not, and then the few services that do appear absorb the
whole day's demand.

Ashford to St Pancras is the worked example. It carries 1,682 journeys a day, and
across four sampled Tuesdays **not one service in this dataset calls at both
stations** — Southeastern's HS1 services are not present as through-services.
When a charter finally did, it was handed all 1,682 passengers, and being
cancelled was charged the full two-hour wait for each: 10,440 passenger-hours
from a single train.

The cause is not knowable from the data, but the symptom is: if dividing a pair's
demand by the services carrying it implies more passengers than a train can hold,
the service count is wrong. Those pairs are dropped rather than guessed at, and
`national.sql` reports `excluded_pairs` and `excluded_journeys` so the omission
stays visible.

On 2026-09-01 that excluded 5 pairs and 7,117 journeys — 0.23% of the day's
estimated total. All five were high-demand pairs showing exactly one service:
three on HS1, one Elizabeth line, one Heathrow. Watch the excluded share: if it
climbs, the upstream service data is losing coverage, not the railway improving.

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
passenger_hours        190,565
hours_delays          140,350   (74%)
hours_cancellations    50,215   (26%)
services               23,582
journeys_estimated  3,069,016
excluded_pairs              5
excluded_journeys       7,117
```

That is 2026-09-01. About 3.7 minutes lost per journey made. The per-operator view is where it gets
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
