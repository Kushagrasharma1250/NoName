Intelligence Platform — Feature Specification

1. Product Overview:
The platform is a multi-source Industrial Fires and Persistent Thermal Sources intelligence system that combines NASA FIRMS detections with satellite, geospatial, and contextual data to classify thermal events, estimate risk, and surface actionable information to users.

2. Core Feature Set

2.1 Multi-Source Satellite Data Ingestion:
a) NASA FIRMS (VIIRS)

Active-fire / thermal anomaly detections

Location, acquisition time, confidence and related fire attributes

b) INSAT

High-frequency thermal observations for rapid temporal monitoring

Useful for tracking evolving thermal activity between lower-frequency observations

c) Sentinel-3

Optical + thermal contextual imagery where available

d) High-resolution imagery / verification layer

Optional visual verification for selected incidents

Intended as a supporting evidence layer rather than the primary detection source

2.2 Geospatial Contextualization:

a) OpenStreetMap (OSM)

Roads

Buildings

Industrial points of interest

Proximity and accessibility context around detected events

b) ESA WorldCover (10 m)

Land-cover classification around each event

Used as a stable baseline contextual layer / fuel-type proxy

c) Industrial / critical-facility databases

Factories

Refineries

Power plants

Mines

Other relevant facilities

d) Spatial preprocessing

Coordinate-system alignment

Raster/vector alignment

Buffering and spatial joins

Feature extraction using GeoPandas, Rasterio and GDAL where appropriate

2.3 Spatial + Temporal Feature Engineering

The platform derives model-ready features from all available sources, including:

1)Temperature / thermal anomaly indicators

2)Land-cover type and land-cover proportions

3)Distance / proximity to roads, buildings and industrial infrastructure

4)Temporal persistence of thermal detections

5)Spatial clustering / hotspot density and spatial pattern

6)Historical behaviour around the location

7)Recent optical/spectral indicators from Sentinel-2

2.4 AI-Based Event Classification

ML/CV models classify detected thermal events into categories such as:

Industrial fire

Wildfire

Agricultural burning

Gas flare

Mining-related thermal activity

Other thermal sources

Candidate MVP models include Random Forest and XGBoost. CNN-based image models can be evaluated later when a sufficiently labelled imagery dataset is available.

