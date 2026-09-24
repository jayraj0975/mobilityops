"""Real-time views: a replay of held-out days on a shared clock, and genuinely live public feeds.

Two different things are streamed, and every message says which is which:

* **replay**: the model's out-of-sample forecasts and the actual pickups for the held-out test days,
  advanced one hour of data every few seconds on a clock shared by every viewer. The taxi files are
  published monthly, so no live taxi feed exists; this is a REPLAY of the past, labelled as such.
* **feeds**: live public data (Citi Bike station availability from the GBFS feed, current weather
  from the National Weather Service), polled only while someone is watching.
"""
