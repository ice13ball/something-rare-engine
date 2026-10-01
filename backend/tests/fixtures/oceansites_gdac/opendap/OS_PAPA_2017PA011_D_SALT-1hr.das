Attributes {
    TIME {
        String long_name "time";
        String standard_name "time";
        String units "days since 1950-01-01T00:00:00Z";
        Float64 valid_min 24637.166666666628;
        Float64 valid_max 25046.666666666628;
        String point_spacing "even";
        String QC_indicator "Good data";
        String Processing_level "Ranges applied, bad data flagged";
        String Uncertainty "None";
        String axis "T";
        Int32 _ChunkSizes 524288;
    }
    LATITUDE {
        String long_name "Anchor Latitude";
        String standard_name "latitude";
        String units "degrees_north";
        Float64 valid_min -90.0;
        Float64 valid_max 90.0;
        String QC_indicator "nominal vlaue";
        String Processing_level "Data manually reviewed";
        String Uncertainty "None";
        String axis "Y";
        String reference "WGS84";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::4326";
        Int32 _ChunkSizes 1;
    }
    LONGITUDE {
        String long_name "Anchor Longitude";
        String standard_name "longitude";
        String units "degrees_east";
        Float64 valid_min -180.0;
        Float64 valid_max 180.0;
        String QC_indicator "nominal value";
        String Processing_level "Data manually reviewed";
        String Uncertainty "None";
        String axis "X";
        String reference "WGS84";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::4326";
        Int32 _ChunkSizes 1;
    }
    DEPTH_TEMP {
        String long_name "nominal depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float64 valid_min 1.3;
        Float64 valid_max 300.0;
        String QC_indicator "nominal value";
        String Processing_level "Data manually reviewed";
        String Uncertainty "Approximate value";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
        Int32 _ChunkSizes 17;
    }
    DEPTH_TEMP2 {
        String long_name "nominal depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float64 valid_min 1.3;
        Float64 valid_max 1.3;
        String QC_indicator "nominal value";
        String Processing_level "Data manually reviewed";
        String Uncertainty "Approximate value";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
        Int32 _ChunkSizes 1;
    }
    DEPTH_PRES {
        String long_name "nominal depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float64 valid_min 5.0;
        Float64 valid_max 300.0;
        String QC_indicator "nominal value";
        String Processing_level "Data manually reviewed";
        String Uncertainty "Approximate value";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
        Int32 _ChunkSizes 3;
    }
    DEPTH_CNDC {
        String long_name "nominal depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float64 valid_min 1.3;
        Float64 valid_max 200.0;
        String QC_indicator "nominal value";
        String Processing_level "Data manually reviewed";
        String Uncertainty "Approximate value";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
        Int32 _ChunkSizes 14;
    }
    DEPTH_CNDC2 {
        String long_name "nominal depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float64 valid_min 1.3;
        Float64 valid_max 1.3;
        String QC_indicator "nominal value";
        String Processing_level "Data manually reviewed";
        String Uncertainty "Approximate value";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
        Int32 _ChunkSizes 1;
    }
    DEPTH_PSAL {
        String long_name "nominal depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float64 valid_min 1.3;
        Float64 valid_max 200.0;
        String QC_indicator "nominal value";
        String Processing_level "Data manually reviewed";
        String Uncertainty "Approximate value";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
        Int32 _ChunkSizes 14;
    }
    DEPTH_PSAL2 {
        String long_name "nominal depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float64 valid_min 1.3;
        Float64 valid_max 1.3;
        String QC_indicator "nominal value";
        String Processing_level "Data manually reviewed";
        String Uncertainty "Approximate value";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
        Int32 _ChunkSizes 1;
    }
    DEPTH_DENS {
        String long_name "nominal depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float64 valid_min 1.3;
        Float64 valid_max 200.0;
        String QC_indicator "nominal value";
        String Processing_level "Data manually reviewed";
        String Uncertainty "Approximate value";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
        Int32 _ChunkSizes 14;
    }
    DEPTH_DENS2 {
        String long_name "nominal depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float64 valid_min 1.3;
        Float64 valid_max 1.3;
        String QC_indicator "nominal value";
        String Processing_level "Data manually reviewed";
        String Uncertainty "Approximate value";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
        Int32 _ChunkSizes 1;
    }
    TEMP {
        Float32 _FillValue NaN;
        String long_name "sea water temperature in-situ ITS-90 scale";
        String standard_name "sea_water_temperature";
        String units "degree_Celsius";
        Float64 valid_min -2.0;
        Float64 valid_max 40.0;
        String coordinates "TIME DEPTH_TEMP LATITUDE LONGITUDE";
        String QC_indicator "Good data";
        String Processing_level "Data manually reviewed";
        String ancillary_variables "TEMP_QC";
        String reference_scale "ITS-90";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "SBE37S, SBE39TP, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE39TP, SBE37TC, SBE39TP";
        String sensor_serial_number "7089 4380 6075 13248 12550 8419 8420 6140 8422 8423 8424 6072 6073 6074 4863 7788 4864 ";
        Int32 _ChunkSizes 1, 17, 1, 1;
    }
    TEMP_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Byte flag_values 0, 1, 2, 3, 4, 7, 8, 9;
        String flag_meanings "unknown good_data probably_good_data bad_data_that_are_potentially_correctable bad_data nominal_value interpolated_value missing_value";
        Int16 _FillValue -128;
        Int32 _ChunkSizes 1, 17, 1, 1;
    }
    PRES {
        Float32 _FillValue NaN;
        String long_name "sea water pressure";
        String standard_name "sea_water_pressure";
        String units "decibar";
        Float64 valid_min 0.0;
        Float64 valid_max 600.0;
        String coordinates "TIME DEPTH_PRES LATITUDE LONGITUDE";
        String QC_indicator "Good data";
        String Processing_level "Data manually reviewed";
        String ancillary_variables "PRES_QC";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "SBE39TP, SBE39TP, SBE39TP";
        String sensor_serial_number "2687064 2862258 2862259 ";
        Int32 _ChunkSizes 1, 3, 1, 1;
    }
    PRES_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Byte flag_values 0, 1, 2, 3, 4, 7, 8, 9;
        String flag_meanings "unknown good_data probably_good_data bad_data_that_are_potentially_correctable bad_data nominal_value interpolated_value missing_value";
        Int16 _FillValue -128;
        Int32 _ChunkSizes 1, 3, 1, 1;
    }
    CNDC {
        Float32 _FillValue NaN;
        String long_name "sea water conductivity";
        String standard_name "sea_water_electrical_conductivity";
        String units "S/m";
        Float64 valid_min 0.0;
        Float64 valid_max 7.0;
        String coordinates "TIME DEPTH_CNDC LATITUDE LONGITUDE";
        String QC_indicator "Good data";
        String Processing_level "Data manually reviewed";
        String ancillary_variables "CNDC_QC";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "SBE37S, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC";
        String sensor_serial_number "7089 6075 13248 12550 8419 8420 6140 8422 8423 8424 6072 6073 6074 7788 ";
        Int32 _ChunkSizes 1, 14, 1, 1;
    }
    CNDC_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Byte flag_values 0, 1, 2, 3, 4, 7, 8, 9;
        String flag_meanings "unknown good_data probably_good_data bad_data_that_are_potentially_correctable bad_data nominal_value interpolated_value missing_value";
        Int16 _FillValue -128;
        Int32 _ChunkSizes 1, 14, 1, 1;
    }
    DENS {
        Float32 _FillValue NaN;
        String long_name "sigma-theta (potential density adjusted to the surface)";
        String standard_name "sea_water_sigma_theta";
        String units "kg m-3";
        Float64 valid_min 0.0;
        Float64 valid_max 100.0;
        String coordinates "TIME DEPTH_DENS LATITUDE LONGITUDE";
        String QC_indicator "Good data";
        String Processing_level "Data manually reviewed";
        String ancillary_variables "DENS_QC";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "SBE37S, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC";
        String sensor_serial_number "7089 6075 13248 12550 8419 8420 6140 8422 8423 8424 6072 6073 6074 7788 ";
        String comment "Derived from measured conductivity, temperature, and pressure (nominal, if not available).";
        Int32 _ChunkSizes 1, 14, 1, 1;
    }
    DENS_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Byte flag_values 0, 1, 2, 3, 4, 7, 8, 9;
        String flag_meanings "unknown good_data probably_good_data bad_data_that_are_potentially_correctable bad_data nominal_value interpolated_value missing_value";
        Int16 _FillValue -128;
        Int32 _ChunkSizes 1, 14, 1, 1;
    }
    PSAL {
        Float32 _FillValue NaN;
        String long_name "sea water salinity";
        String standard_name "sea_water_practical_salinity";
        String units "1";
        Float64 valid_min 25.0;
        Float64 valid_max 45.0;
        String coordinates "TIME DEPTH_PSAL LATITUDE LONGITUDE";
        String QC_indicator "Good data";
        String Processing_level "Data manually reviewed";
        String ancillary_variables "PSAL_QC";
        String reference_scale "PSS-78";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "SBE37S, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC, SBE37TC";
        String sensor_serial_number "7089 6075 13248 12550 8419 8420 6140 8422 8423 8424 6072 6073 6074 7788 ";
        String comment "In PSU. Derived from measured conductivity, temperature, and pressure (nominal, if not available).";
        Int32 _ChunkSizes 1, 14, 1, 1;
    }
    PSAL_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Byte flag_values 0, 1, 2, 3, 4, 7, 8, 9;
        String flag_meanings "unknown good_data probably_good_data bad_data_that_are_potentially_correctable bad_data nominal_value interpolated_value missing_value";
        Int16 _FillValue -128;
        Int32 _ChunkSizes 1, 14, 1, 1;
    }
    TEMP2 {
        Float32 _FillValue NaN;
        String long_name "sea water temperature in-situ ITS-90 scale";
        String standard_name "sea_water_temperature";
        String units "degree_Celsius";
        Float64 valid_min -2.0;
        Float64 valid_max 40.0;
        String coordinates "TIME DEPTH_TEMP2 LATITUDE LONGITUDE";
        String QC_indicator "Good data";
        String Processing_level "Data manually reviewed";
        String ancillary_variables "TEMP2_QC";
        String reference_scale "ITS-90";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "SBE37S";
        String sensor_serial_number "7090 ";
        String comment "Secondary Instrument.";
        Int32 _ChunkSizes 1, 1, 1, 1;
    }
    TEMP2_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Byte flag_values 0, 1, 2, 3, 4, 7, 8, 9;
        String flag_meanings "unknown good_data probably_good_data bad_data_that_are_potentially_correctable bad_data nominal_value interpolated_value missing_value";
        Int16 _FillValue -128;
        Int32 _ChunkSizes 1, 1, 1, 1;
    }
    CNDC2 {
        Float32 _FillValue NaN;
        String long_name "sea water conductivity";
        String standard_name "sea_water_electrical_conductivity";
        String units "S/m";
        Float64 valid_min 0.0;
        Float64 valid_max 7.0;
        String coordinates "TIME DEPTH_CNDC2 LATITUDE LONGITUDE";
        String QC_indicator "Good data";
        String Processing_level "Data manually reviewed";
        String ancillary_variables "CNDC2_QC";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "SBE37S";
        String sensor_serial_number "7090 ";
        String comment "Secondary Instrument.";
        Int32 _ChunkSizes 1, 1, 1, 1;
    }
    CNDC2_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Byte flag_values 0, 1, 2, 3, 4, 7, 8, 9;
        String flag_meanings "unknown good_data probably_good_data bad_data_that_are_potentially_correctable bad_data nominal_value interpolated_value missing_value";
        Int16 _FillValue -128;
        Int32 _ChunkSizes 1, 1, 1, 1;
    }
    DENS2 {
        Float32 _FillValue NaN;
        String long_name "sigma-theta (potential density adjusted to the surface)";
        String standard_name "sea_water_sigma_theta";
        String units "kg m-3";
        Float64 valid_min 0.0;
        Float64 valid_max 100.0;
        String coordinates "TIME DEPTH_DENS2 LATITUDE LONGITUDE";
        String QC_indicator "Good data";
        String Processing_level "Data manually reviewed";
        String ancillary_variables "DENS2_QC";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "SBE37S";
        String sensor_serial_number "7090 ";
        String comment "Derived from measured conductivity, temperature, and pressure (nominal, if not available). Secondary Instrument.";
        Int32 _ChunkSizes 1, 1, 1, 1;
    }
    DENS2_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Byte flag_values 0, 1, 2, 3, 4, 7, 8, 9;
        String flag_meanings "unknown good_data probably_good_data bad_data_that_are_potentially_correctable bad_data nominal_value interpolated_value missing_value";
        Int16 _FillValue -128;
        Int32 _ChunkSizes 1, 1, 1, 1;
    }
    PSAL2 {
        Float32 _FillValue NaN;
        String long_name "sea water salinity";
        String standard_name "sea_water_practical_salinity";
        String units "1";
        Float64 valid_min 25.0;
        Float64 valid_max 45.0;
        String coordinates "TIME DEPTH_PSAL2 LATITUDE LONGITUDE";
        String QC_indicator "Good data";
        String Processing_level "Data manually reviewed";
        String ancillary_variables "PSAL2_QC";
        String reference_scale "PSS-78";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "SBE37S";
        String sensor_serial_number "7090 ";
        String comment "In PSU. Derived from measured conductivity, temperature, and pressure (nominal, if not available). Secondary Instrument.";
        Int32 _ChunkSizes 1, 1, 1, 1;
    }
    PSAL2_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Byte flag_values 0, 1, 2, 3, 4, 7, 8, 9;
        String flag_meanings "unknown good_data probably_good_data bad_data_that_are_potentially_correctable bad_data nominal_value interpolated_value missing_value";
        Int16 _FillValue -128;
        Int32 _ChunkSizes 1, 1, 1, 1;
    }
    NC_GLOBAL {
        String comment "The bridle SSTC instrument depth is copied from the PMEL metadata database. The actual depth is closer to 1.2m.";
        String data_type "OceanSITES time-series data";
        String format_version "1.3";
        String date_created "2019-01-29T16:24:37Z";
        String date_modified "2019-01-29T16:24:37Z";
        String institution "NOAA/Pacific Marine Environmental Laboratory";
        String project "Ocean Climate Stations (OCS)";
        String network "OCS";
        String wmo_platform_code "4800400";
        String source "Moored surface buoy";
        String history "2019-01-29T16:24:37Z data updated at PMEL";
        String data_mode "D";
        String QC_indicator "excellent";
        String processing_level "Ranges applied, bad data flagged";
        String references "http://www.oceansites.org, http://www.pmel.noaa.gov/OCS/";
        String Conventions "OceanSITES Manual 1.3, CF-1.6";
        String netcdf_version "4.3.3.1";
        String naming_authority "OceanSITES";
        String id "OS_PAPA_2017PA011_D_SALT-1hr";
        String cdm_data_type "Station";
        String time_coverage_start "2017-06-15T04:00:00Z";
        String time_coverage_end "2018-07-29T16:00:00Z";
        String institution_references "http://www.pmel.noaa.gov/";
        String contact "redacted";
        String publisher_name "redacted";
        String publisher_email "redacted";
        String publisher_url "redacted";
        String data_assembly_center "PMEL";
        String principal_investigator "redacted";
        String principal_investigator_email "redacted";
        String principal_investigator_url "redacted";
        String license "These data are made freely available without restriction";
        String citation "These data were collected and made freely available by the OceanSITES project and the Ocean Climate Stations (OCS) Project Office of NOAA/PMEL";
        String update_interval "void";
        String qc_manual "http://www.oceansites.org/docs/oceansites_data_format_reference_manual.pdf";
        String Data_Source "OCS Project Office/NOAA/PMEL";
        String acknowledgement "redacted";
        String platform_code "PAPA";
        String site_code "PAPA";
        String array "STATION-P";
        String title "OceanSITES Station PAPA In-Situ Hourly Resolution Data";
        String geospatial_lon_min "-145.00";
        String geospatial_lon_max "-144.70";
        String geospatial_lat_min "50.00";
        String geospatial_lat_max "50.20";
        String area "North Pacific";
        String geospatial_vertical_min "1";
        String geospatial_vertical_max "300";
        String geospatial_vertical_positive "down";
        String summary "This file contains hourly resolution delayed-mode in-situ data from the upper-ocean SBE instruments on the OceanSITES Station PAPA (nominally 50.1N, 144.9W) 2017 (PA011) deployment.";
    }
    DODS_EXTRA {
        String Unlimited_Dimension "TIME";
    }
}
