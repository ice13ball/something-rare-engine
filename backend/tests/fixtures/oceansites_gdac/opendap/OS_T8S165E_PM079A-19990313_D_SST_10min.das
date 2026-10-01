Attributes {
    TIME {
        String standard_name "time";
        String long_name "Time";
        String units "days since 1950-01-01T00:00:00Z";
        Float32 valid_min 0.0;
        Float32 valid_max 54750.0;
        String comment "Julian days relative to 1950-01-1T00:00:00Z with decimal part as parts of the day";
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
    SST {
        String standard_name "sea_surface_temperature";
        String long_name "Sea Surface Temperature";
        String units "degree_Celsius";
        Float32 _FillValue -999.0;
        Float32 valid_min -5.0;
        Float32 valid_max 35.0;
        Float32 accuracy 0.003;
        Float32 resolution 0.001;
        String sensor_name "Thermistor [Seabird/SBE 16/37]";
        String sensor_serial_number "SST-11633/1m ";
        String ancillary_variables "SST_QC SST_DM";
        String cell_methods "TIME:point DEPTH:point LATITUDE:point LONGITUDE:point";
        String reference_scale "ITS-90";
        String coordinates "TIME DEPTH LATITUDE LONGITUDE";
    }
    SST_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        Int16 _FillValue -1;
        Byte valid_min 0;
        Byte valid_max 9;
        Byte flag_values 0, 1, 2, 3, 4, 5, 9;
        String flag_meanings "unknown good_data probably_good_data questionable_data bad_data adjusted_data missing_data";
        String coordinates "TIME DEPTH LATITUDE LONGITUDE";
    }
    SST_DM {
        String long_name "data mode";
        String flag_values "R, P, D, M";
        String flag_meanings "real-time provisional delayed-mode mixed";
        String coordinates "TIME DEPTH LATITUDE LONGITUDE";
        DODS {
            Int32 strlen 1;
            String dimName "DEPTH";
        }
    }
    NC_GLOBAL {
        String time_coverage_start "1999-03-13T07:00:00Z";
        String time_coverage_end "1999-08-13T22:40:00Z";
        String featureType "timeSeries";
        String format_version "1.3";
        String platform_code "T8S165E";
        String platform_type "ATLAS";
        String site_code "T8S165E";
        String network "TAO";
        String wmo_platform_code "52007";
        String title "TAO Delayed/Mixed Mode Data";
        String summary "Delayed/Mixed mode data from NDBC Tropical Atmosphere Ocean (TAO) Array";
        String source "subsurface mooring";
        String keywords "EARTH SCIENCE > OCEANS > OCEAN TEMPERATURE > WATER TEMPERATURE, SEA SURFACE TEMPERATURE; EARTH SCIENCE > CLIMATE INDICATORS > ATMOSPHERIC/OCEAN INDICATORS > TELECONNECTIONS > EL NINO SOUTHERN OSCILLATION (ENSO), ENSO;";
        String keywords_vocabulary "GCMD Science Keywords";
        String data_mode "D";
        String Conventions "CF-1.6, OceanSITES 1.3";
        String netcdf_version "NetCDF-4 classic";
        String naming_authority "NOAA/NDBC";
        String id "TAO_T8S165E_PM079A-19990313_D_SST_10min";
        String cdm_data_type "Station";
        String area "Tropical Pacific Ocean";
        String geospatial_lat_units "degrees_north";
        String geospatial_lon_units "degrees_east";
        String geospatial_lat_min "-8.0";
        String geospatial_lat_max "-8.0";
        String geospatial_lon_min "165.0";
        String geospatial_lon_max "165.0";
        String geospatial_vertical_positive "down";
        String geospatial_vertical_units "meters";
        String geospatial_vertical_min "0";
        String geospatial_vertical_max "500";
        String citation "These data were collected and made freely available by National Data Buoy Center (NDBC).";
        String update_interval "void";
        String program "NOAA/NDBC/TAO";
        String references "http://tao.noaa.gov";
        String principal_investigator "redacted";
        String institution "NOAA/National Data Buoy Center (NDBC), U.S.";
        String institution_references "http://www.ndbc.noaa.gov";
        String data_assembly_center "NDBC";
        String publisher_name "redacted";
        String publisher_email "redacted";
        String date_created "2014-02-18T16:51:40Z";
        String date_modified "2014-02-18T16:51:40Z";
        String processing_level "Data manually reviewed";
        String history "2014-02-18T16:51:40Z data and metadata assembled, JZ.";
    }
    DODS_EXTRA {
        String Unlimited_Dimension "TIME";
    }
}
