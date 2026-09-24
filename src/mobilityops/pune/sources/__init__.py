"""Source adapters. Each one fetches, validates and returns typed records with the source's own
timestamp; none of them invents data. A failing source raises :class:`SourceError` and the caller
records the failure rather than substituting a value."""
