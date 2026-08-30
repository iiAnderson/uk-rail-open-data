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
- **Reason codes are sparse.** Darwin supplies a reason on a minority of
  services. On a typical day around 70% of lost time has no stated cause, so
  treat the reason ranking as relative, not as a complete account.
- **Loading data is partial.** `avg_loading` is only reported by some operators,
  so it is not comparable across the whole network.
- See [Known gaps](README.md#known-gaps) for dates where the pipeline failed.
