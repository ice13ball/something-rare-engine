Attributes {
    TIME {
        String standard_name "time";
        String long_name "Time";
        String units "days since 1950-01-01T00:00:00Z";
        Float32 valid_min 0.0;
        Float32 valid_max 54750.0;
        String comment "Julian days relative to 1950-01-01T00:00:00Z with decimal part as parts of the day";
        String axis "T";
    }
    DEPTH {
        String standard_name "depth";
        String long_name "Nominal depth of each measurement";
        String units "meters";
        Float32 valid_min 0.0;
        Float32 valid_max 500.0;
        String axis "Z";
        String positive "down";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
    }
    LATITUDE {
        String standard_name "latitude";
        String long_name "Nominal latitude at the location";
        String units "degrees_north";
        Float32 valid_min -90.0;
        Float32 valid_max 90.0;
        String axis "Y";
        String reference "WGS84";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::4326";
    }
    LONGITUDE {
        String standard_name "longitude";
        String long_name "Nominal longitude at the location";
        String units "degrees_east";
        Float32 valid_min -180.0;
        Float32 valid_max 180.0;
        String axis "X";
        String reference "WGS84";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::4326";
    }
    TEMP {
        String standard_name "sea_water_temperature";
        String long_name "Sea Water Temperature";
        String units "degree_Celsius";
        Float32 _FillValue -999.0;
        Float32 valid_min -5.0;
        Float32 valid_max 35.0;
        Float32 accuracy 0.003;
        Float32 resolution 0.001;
        String sensor_name "Thermistor [Seabird/SBE 16/37]";
        String sensor_serial_number "3289/1m 4416/5m 4398/10m 2810/20m 6937/25m 4886/40m 6943/45m 2811/60m 4414/80m 6941/100m 4411/120m 6940/140m 6911/180m 4069/300m 4954/500m";
        String ancillary_variables "TEMP_QC TEMP_DM";
        String cell_methods "TIME:point DEPTH:point LATITUDE:point LONGITUDE:point";
        String reference_scale "ITS-90";
        String coordinates "TIME DEPTH LATITUDE LONGITUDE";
    }
    TEMP_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        Int16 _FillValue -1;
        Byte valid_min 0;
        Byte valid_max 9;
        Byte flag_values 0, 1, 2, 3, 4, 5, 9;
        String flag_meanings "unknown good_data probably_good_data questionable_data bad_data adjusted_data missing_data";
        String coordinates "TIME DEPTH LATITUDE LONGITUDE";
    }
    TEMP_DM {
        String long_name "data mode";
        String flag_values "R, D";
        String flag_meanings "real-time delayed-mode";
        String coordinates "TIME DEPTH LATITUDE LONGITUDE";
        DODS {
            Int32 strlen 15;
            String dimName "DEPTH";
        }
    }
    NC_GLOBAL {
        String time_coverage_start "2014-09-16T03:50:00Z";
        String time_coverage_end "2015-03-22T16:30:00Z";
        String featureType "timeSeriesProfile";
        String format_version "1.3";
        String platform_code "T0N140W";
        String platform_type "TAO Refresh";
        String site_code "T0N140W";
        String network "TAO";
        String wmo_platform_code "51311";
        String update_interval "void";
        String title "TAO Delayed/Mixed Mode Data";
        String summary "Delayed/Mixed mode data from NDBC Tropical Atmosphere Ocean (TAO) Array";
        String source "subsurface mooring";
        String keywords "EARTH SCIENCE > OCEANS > OCEAN TEMPERATURE > WATER TEMPERATURE; EARTH SCIENCE > OCEANS > OCEAN TEMPERATURE > SEA SURFACE TEMPERATURE; EARTH SCIENCE > CLIMATE INDICATORS > ATMOSPHERIC/OCEAN INDICATORS > TELECONNECTIONS; EARTH SCIENCE > CLIMATE INDICATORS > ATMOSPHERIC/OCEAN INDICATORS > SEA SURFACE TEMPERATURE INDICES > OCEANIC NINO INDEX; EARTH SCIENCE > CLIMATE INDICATORS > ATMOSPHERIC/OCEAN INDICATORS > TELECONNECTIONS > EL NINO SOUTHERN OSCILLATION (ENSO) > ENSO;";
        String keywords_vocabulary "GCMD Science Keywords";
        String data_mode "D";
        String Conventions "CF-1.6, OceanSITES 1.3";
        String netcdf_version "NetCDF-4 classic";
        String naming_authority "NOAA/NDBC";
        String id "TAO_T0N140W_DM092A-20140916_D_TEMP_10min";
        String cdm_data_type "Station";
        String area "Tropical Pacific Ocean";
        String geospatial_lat_units "degrees_north";
        String geospatial_lon_units "degrees_east";
        String geospatial_lat_min "0.0";
        String geospatial_lat_max "0.0";
        String geospatial_lon_min "-140.0";
        String geospatial_lon_max "-140.0";
        String geospatial_vertical_positive "down";
        String geospatial_vertical_units "meters";
        String geospatial_vertical_min "0";
        String geospatial_vertical_max "500";
        String citation "These data were collected and made freely available by National Data Buoy Center (NDBC).";
        String program "NOAA/NDBC/TAO";
        String references "https://tao.ndbc.noaa.gov";
        String principal_investigator "redacted";
        String institution "NOAA/National Data Buoy Center (NDBC), U.S.";
        String institution_references "https://www.ndbc.noaa.gov";
        String data_assembly_center "NDBC";
        String publisher_name "redacted";
        String publisher_email "redacted";
        String date_created "2019-03-08T15:03:48Z";
        String date_modified "2019-03-08T15:03:48Z";
        String processing_level "Data manually reviewed";
        String history "2019-03-08T15:03:48Z data and metadata assembled, JZ.";
    }
    DODS_EXTRA {
        String Unlimited_Dimension "TIME";
    }
}
