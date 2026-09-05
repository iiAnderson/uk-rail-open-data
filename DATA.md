# Data provenance and terms

**The MIT licence in this repository covers the code, not the data.**

## Where it comes from

The dataset derives from the National Rail **Darwin** push port feed, obtained
under National Rail Enquiries' open data terms. Darwin publishes schedules,
running forecasts and actual times for passenger services on the GB network.

Station journey volumes in `odm_v1` are origin-destination counts published for
the rail industry, used here to weight services by how many people travel them.

## Attribution

If you use this data, or anything derived from it, acknowledge the source:

> Contains information from National Rail Enquiries.

## Your obligations

Darwin's terms are based on the Open Government Licence v2.0 with amendments
specific to National Rail Enquiries. Two things worth knowing:

1. **Attribution is required**, as above.
2. **Forecast consistency**: products that display predicted arrival or departure
   times must not contradict Darwin's own forecasts. This dataset is historical
   and aggregate, so it does not engage that clause — but a product you build on
   top of it might.

You are responsible for your own compliance. If you need the live feed rather
than this archive, subscribe directly through the
[Rail Data Marketplace](https://raildata.org.uk/) — access is granted per
account and is not transferable.

## What this archive adds

The underlying observations are facts and belong to nobody. What this repository
publishes is a compilation: continuous collection since January 2025,
verification against a second source to recover cancellation reasons, and
normalisation into one row per service with a stop-level array. Please credit it
rather than passing it off, and read the upstream terms before redistributing it
in bulk.

## Methodological caveats

Worth knowing before you quote a number:

- **Journey volumes are from financial year 2024/25**, the latest published. They
  weight *relative* demand between station pairs. They are not a current traffic
  estimate, and they do not reflect demand changes since.
- **Passenger loads are modelled, not counted.** An annual O-D total is divided
  by the number of services offering that pair on the day, which spreads demand
  evenly across the timetable. That under-weights the peak and over-weights the
  middle of the day.
- **Some station pairs are dropped entirely.** Where the service data does not
  show enough trains to carry a pair's known demand, that pair is excluded rather
  than have its passengers attributed to whichever service happened to appear.
  This slightly understates the total. `latest.json` carries the excluded counts;
  see [queries/README.md](queries/README.md#the-coverage-guard).
- **Reason codes are sparse.** Darwin supplies a reason on a minority of
  services. On a typical day around 70% of lost time has no stated cause, so
  treat the reason ranking as relative, not as a complete account.
- **Loading data is partial.** `avg_loading` is only reported by some operators,
  so it is not comparable across the whole network.
- **Track attribution is inferred, not recorded.** Darwin says where a service
  stopped and what it was booked to pass through; it does not say which line it
  took. The map matches a service to a section of track when its route touches
  the stations on that section, and joins consecutive stops by walking the
  network graph. Where two routes are plausible it will have picked one. Read a
  section's figures as the traffic that almost certainly ran over it, not as a
  signalling record.
- **Cancellations are attributed to the part of the journey that was lost.** A
  service curtailed at Reading counts as cancelled west of Reading and as a
  running, possibly late, train east of it. Totals therefore differ from a
  service-level cancellation rate, and deliberately so: a track section that
  kept its trains did not lose them.
- See [Known gaps](README.md#known-gaps) for dates where the pipeline failed.
