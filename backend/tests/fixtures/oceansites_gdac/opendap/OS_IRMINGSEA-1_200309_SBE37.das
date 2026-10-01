Attributes {
    TIME {
        String standard_name "time";
        String units "days since 1950-01-01T00:00:00Z";
        String axis "T";
        String long_name "time of measurement";
        String conventions "Relative julian days with decimal part (as parts of the day)";
        Float32 valid_min 0.0;
        Float32 valid_max 90000.0;
        String QC_indicator "good data";
        String processing_level "Data manually reviewed";
    }
    LATITUDE {
        String standard_name "latitude";
        String units "degrees_north";
        String axis "Y";
        String long_name "Latitude of measurement";
        String reference "WGS84";
        String coordinate_reference_frame "urn:ogc:def:crs:EPSG::4326";
        Float64 valid_min -90.0;
        Float64 valid_max 90.0;
        String QC_indicator "good data";
        String processing_level "Data manually reviewed";
        Float64 uncertainty 0.004;
        String comment "n/a";
    }
    LONGITUDE {
        String long_name "Longitude of each location";
        String standard_name "longitude";
        String units "degrees_east";
        String axis "X";
        String reference "WGS84";
        String coordinate_reference_frame "urn:ogc:def:crs:EPSG::4326";
        Float64 valid_min -180.0;
        Float64 valid_max 180.0;
        String QC_indicator "good data";
        String processing_level "Data manually reviewed";
        Float64 uncertainty 0.004;
        String comment "n/a";
    }
    DEPTH {
        String standard_name "depth";
        String units "meters";
        String positive "down";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5831";
        String long_name "Depth of measurement (instrument depth)";
        Float64 valid_min 0.0;
        Float64 valid_max 12000.0;
        String QC_indicator "nominal value";
        String processing_level "Data manually reviewed";
        Float64 uncertainty 1.0;
        String comment "nominal depth - use PRES to derive time-varying depth";
    }
    PRES {
        String standard_name "sea_water_pressure";
        String units "decibar";
        Float32 _FillValue 99999.0;
        String coordinates "TIME LATITUDE LONGITUDE DEPTH";
        String long_name "pressure of each measurement";
        String QC_indicator "good data";
        String processing_level "Data manually reviewed";
        String positive "down";
        Float64 valid_min 0.0;
        Float64 valid_max 12000.0;
        Float64 uncertainty 50.0;
        Float64 accuracy 7.0;
        String precision "stability 0.004%FS/month";
        Float64 resolution 0.14;
        String DM_indicator "D";
        String comment "n/a";
        String axis "Z";
        String reference_scale "mean_sea_level";
        String sensor_model "SBE37-SM Microcat";
        String sensor_manufacturer "Sea-Bird Electronics Inc";
        String sensor_reference "http://www.seabird.com/pdf_documents/Datasheets/37SMbrochureMar14.pdf";
        String sensor_serial_number "2675";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_orientation "vertical";
    }
    TEMP {
        String standard_name "sea_water_temperature";
        String units "degree_Celsius";
        Float32 _FillValue 99999.0;
        String coordinates "TIME LATITUDE LONGITUDE DEPTH";
        String long_name "sea water temperature";
        String QC_indicator "good data";
        String processing_level "Data manually reviewed";
        Float64 valid_min -2.5;
        Float64 valid_max 40.0;
        Float64 uncertainty 0.01;
        Float64 accuracy 0.005;
        Float64 precision 5.0E-4;
        Float64 resolution 1.0E-4;
        String DM_indicator "D";
        String comment "In-situ measurement";
        String reference_scale "ITS-90";
        String sensor_model "SBE37-SM Microcat";
        String sensor_manufacturer "Sea-Bird Electronics Inc";
        String sensor_reference "http://www.seabird.com/pdf_documents/Datasheets/37SMbrochureMar14.pdf";
        String sensor_serial_number "2675";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_orientation "vertical";
    }
    CNDC {
        String standard_name "sea_water_electrical_conductivity";
        String units "S m-1";
        Float32 _FillValue 99999.0;
        String coordinates "TIME LATITUDE LONGITUDE DEPTH";
        String long_name "sea water conductivity";
        String QC_indicator "good data";
        String processing_level "Data manually reviewed";
        Float64 valid_min 0.0;
        Float64 valid_max 7.0;
        Float64 accuracy 3.0E-4;
        Float64 resolution 1.0E-5;
        String DM_indicator "D";
        String comment "In-situ measurement";
        String reference_scale "ITS-90";
        String sensor_model "SBE37-SM Microcat";
        String sensor_manufacturer "Sea-Bird Electronics Inc";
        String sensor_reference "http://www.seabird.com/pdf_documents/Datasheets/37SMbrochureMar14.pdf";
        String sensor_serial_number "2675";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_orientation "vertical";
    }
    PSAL {
        String standard_name "sea_water_practical_salinity";
        String units "psu";
        Float32 _FillValue 99999.0;
        String coordinates "TIME LATITUDE LONGITUDE DEPTH";
        String long_name "sea water salinity";
        String QC_indicator "good data";
        String processing_level "Data manually reviewed";
        Float64 valid_min 1.0;
        Float64 valid_max 40.0;
        String DM_indicator "D";
        String comment "In-situ measurement";
        String reference_scale "PSS-78";
        String sensor_model "SBE37-SM Microcat";
        String sensor_manufacturer "Sea-Bird Electronics Inc";
        String sensor_reference "http://www.seabird.com/pdf_documents/Datasheets/37SMbrochureMar14.pdf";
        String sensor_serial_number "2675";
        String sensor_mount "mounted_on_mooring_line";
        String sensor_orientation "vertical";
    }
    NC_GLOBAL {
        String site_code "LOCO-IRMINGSEA";
        String platform_code "IRMINGSEA-1";
        String data_mode "D";
        String title "Irminger Sea Microcat sensor data 9/2003-9/2004";
        String summary "water temperature and salinity at nominal depth 2965m";
        String naming_authority "OceanSITES";
        String id "OS_IRMINGSEA-1_200309_SBE37";
        String source "subsurface mooring";
        String principal_investigator "redacted";
        String institution "Royal Netherlands Institute for Sea Research, NIOZ";
        String project "LOCO";
        String array "IRMINGER SEA";
        String network "NACLIM";
        String area "North Atlantic Ocean";
        String geospatial_lat_min "59.4297";
        String geospatial_lat_max "59.4297";
        String geospatial_lat_units "degree_north";
        String geospatial_lon_min "-39.0015";
        String geospatial_lon_max "-39.0015";
        String geospatial_lon_units "degree_east";
        String geospatial_vertical_min "3011.862";
        String geospatial_vertical_max "3017.312";
        String geospatial_vertical_positive "down";
        String geospatial_vertical_units "dbar";
        String time_coverage_start "2003-08-30T12:00:00Z";
        String time_coverage_end "2004-10-01T11:04:02Z";
        String time_coverage_duration "P398D";
        String time_coverage_resolution "PT4M";
        String cdm_data_type "Station";
        String data_type "OceanSITES time-series data";
        String format_version "1.3";
        String Conventions "CF-1.6 OceanSITES-1.3 ACDD-1.2";
        String netcdf_version "4";
        String publisher_name "redacted";
        String publisher_email "redacted";
        String publisher_url "redacted";
        String references "http://www.oceansites.org";
        String data_assembly_center "NIOZ";
        String update_interval "void";
        String license "Follows CLIVAR (Climate Variability and Predictability) standards, cf. http://www.clivar.org/data/data_policy.php. Data available free of charge. User assumes all risk for use of data. User must display citation in any publication or product using data. User must contact PI prior to any commercial use of data.";
        String citation "These data were collected and made freely available by the OceanSITES project and the national programs that contribute to it.";
        String acknowledgement "redacted";
        String date_created "2014-09-29T18:57:47Z";
        String processing_level "Data manually reviewed";
        String QC_indicator "excellent";
        String contributor_name "redacted";
        String contributor_role "data processing and interpretation";
        String history "Thu Mar 29 16:40:16 2018: ncatted -a geospatial_vertical_max,global,o,c,3017.312 /home/coriolis_dev/val/spool/co05/co0527/co052701/gdac/DATA/PatchedNetCDF/OS_IRMINGSEA-1_200309_SBE37.nc
Thu Mar 29 16:40:16 2018: ncatted -a geospatial_vertical_min,global,o,c,3011.862 /home/coriolis_dev/val/spool/co05/co0527/co052701/gdac/DATA/PatchedNetCDF/OS_IRMINGSEA-1_200309_SBE37.nc
Mon Mar 26 17:28:14 2018: ncatted -a geospatial_lon_max,global,o,c,-39.0015 /home3/homedir4/perso/criou/PatchedNetCDF/OS_IRMINGSEA-1_200309_SBE37.nc
Mon Mar 26 17:28:14 2018: ncatted -a geospatial_lon_min,global,o,c,-39.0015 /home3/homedir4/perso/criou/PatchedNetCDF/OS_IRMINGSEA-1_200309_SBE37.nc
Mon Mar 26 17:28:14 2018: ncatted -a geospatial_lat_max,global,o,c,59.4297 /home3/homedir4/perso/criou/PatchedNetCDF/OS_IRMINGSEA-1_200309_SBE37.nc
Mon Mar 26 17:28:14 2018: ncatted -a geospatial_lat_min,global,o,c,59.4297 /home3/homedir4/perso/criou/PatchedNetCDF/OS_IRMINGSEA-1_200309_SBE37.nc";
    }
}
