Attributes {
    TIME {
        String description "Date and Time from Matlab";
        String long_name "time";
        String standard_name "time";
        String units "days since 1950-01-01T00:00:00Z";
        String conventions "Relative julian days with decimal part (as parts of the day)";
        Float32 valid_min 0.0;
        Float32 valid_max 90000.0;
        String QC_indicator "1";
        String QC_procedure "1";
        Float64 uncertainty 5.0E-6;
        String axis "T";
    }
    DEPTH {
        String long_name "Depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float32 valid_min 0.0;
        Float32 valid_max 12000.0;
        String comment "These are nominal values. Use PRES to derive time-varying depths of instruments, as the mooring may tilt in ambient currents.";
        String QC_indicator "1";
        String QC_procedure "1";
        String uncertainty "0";
        String axis "Z";
        String reference "sea_level";
    }
    LATITUDE {
        String QC_indicator "1";
        String QC_procedure "1";
        String long_name "Latitude of each location";
        String standard_name "latitude";
        String units "degrees_north";
        Float32 valid_min -90.0;
        Float32 valid_max 90.0;
        String comment "LATITUDE Latitude for each point";
        String ancillary_variables "LATITUDE_QC";
        Float64 uncertainty 0.05;
        String axis "Y";
    }
    LONGITUDE {
        String QC_indicator "1";
        String QC_procedure "1";
        String long_name "Longitude of each location";
        String standard_name "longitude";
        String units "degrees_east";
        Float32 valid_min -180.0;
        Float32 valid_max 180.0;
        String comment "LONGITUDE Longitude for each point";
        String ancillary_variables "LONGITUDE_QC";
        Float64 uncertainty 0.05;
        String axis "X";
    }
    POSITION {
    }
    TEMP {
        String long_name "Temperature";
        String standard_name "sea_water_temperature";
        String units "degree_Celsius";
        Float32 _FillValue 99999.0;
        Float32 valid_min 2.0;
        Float32 valid_max 100.0;
        String comment "Temperature in Degrees Celsius at nominal depths of 25    38    67   107   152   252   403   603   803  1003 meter(s)";
        String sensor_depth "25, 38, 67, 107, 152, 252, 403, 603, 803, 1003  m(s)";
        String sensor_mount "mounted on mooring line";
        String sensor_orientation "vertical";
        String sensor_name "Seabird:Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor              ";
        String sensor_serial_number "2974, 2486, 954, 2934, 2718, 961, 2809, 3416, 1520, 3415, ";
        String ancillary_variables "TEMP_QC";
        Float64 accuracy 0.003;
        Float64 resolution 0.001;
        String cell_methods "Time:point DEPTH:point LATITUDE:point LONGITUDE:point";
        String DM_indicator "D";
    }
    TEMP_QC {
        String _Unsigned "false";
        String comment "Quality Marker for Temperature in Degrees Celsius at nominal depths of 25    38    67   107   152   252   403   603   803  1003 meter(s)";
        String long_name "quality flag";
        Int16 _FillValue -128;
        Int32 valid_min 0;
        Int32 valid_max 9;
        Float64 flag_values 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 8.0, 9.0;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    CNDC {
        String long_name "sea water electrical conductivity";
        String standard_name "sea_water_electrical_conductivity";
        String units "mS/cm";
        Float32 _FillValue 99999.0;
        Float32 valid_min 25.0;
        Float32 valid_max 45.0;
        String comment "Conductivity in mS/cm at nominal depths of 25    38    67   107   152   252   403   603   803  1003 meter(s)";
        String sensor_depth "50   53   44   32   51   56   44   32   54   55   44   32   49   48   55   44   32   49   53   50   44   32   50   53   50   44   32   52   48   51   44   32   54   48   51   44   32   56   48   51   44   32   49   48   48   51   32   32  109   40  115   41";
        String sensor_mount "mounted on mooring line";
        String sensor_orientation "vertical";
        String sensor_name "Seabird:Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor              ";
        String sensor_serial_number "2974, 2486, 954, 2934, 2718, 961, 2809, 3416, 1520, 3415, ";
        String ancillary_variables "CDNC_QC";
        Float64 accuracy 0.02;
        Float64 resolution 0.001;
        String cell_methods "Time:point DEPTH:point LATITUDE:point LONGITUDE:point";
        String DM_indicator "D";
    }
    CNDC_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        String comment "Quality Marker for each Conductivity in mS/cm at nominal depths of 25    38    67   107   152   252   403   603   803  1003 meter(s)";
        Int16 _FillValue -128;
        Int32 valid_min 0;
        Int32 valid_max 9;
    }
    PRES {
        String long_name "sea_water_pressure";
        String standard_name "sea_water_pressure";
        String units "decibar";
        Float32 _FillValue 99999.0;
        Float32 valid_min 0.0;
        Float32 valid_max 12000.0;
        String comment "PRES (dbar) at nominal depths of 25    38    67   107   152   252   403   603   803  1003 meter(s)";
        String sensor_depth "50   53   44   32   51   56   44   32   54   55   44   32   49   48   55   44   32   49   53   50   44   32   50   53   50   44   32   52   48   51   44   32   54   48   51   44   32   56   48   51   44   32   49   48   48   51   32   32  109   40  115   41";
        String sensor_mount "mounted on mooring line";
        String sensor_orientation "vertical";
        String sensor_name "Seabird:Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor              ";
        String sensor_serial_number "2974, 2486, 954, 2934, 2718, 961, 2809, 3416, 1520, 3415, ";
        String ancillary_variables "PRES_QC";
        Float64 accuracy 0.25;
        Float64 resolution 0.03;
        String cell_methods "Time:point DEPTH:point LATITUDE:point LONGITUDE:point";
        String DM_indicator "D";
        String axis "z";
        String positive "DOWN";
    }
    PRES_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        String comment "Quality Marker for each PRES (dbar) at nominal depths of 25    38    67   107   152   252   403   603   803  1003 meter(s)";
        Int16 _FillValue -128;
        Int32 valid_min 0;
        Int32 valid_max 9;
    }
    PSAL {
        String long_name "sea water salinity";
        String standard_name "sea_water_salinity";
        String units "psu";
        Float32 _FillValue 99999.0;
        Float32 valid_min 29.0;
        Float32 valid_max 40.0;
        String comment "Practical PSAL Units for each nominal depth(s) of 25    38    67   107   152   252   403   603   803  1003 meter(s)";
        String sensor_depth "25, 38, 67, 107, 152, 252, 403, 603, 803, 1003  m(s)";
        String sensor_mount "mounted on mooring line";
        String sensor_orientation "vertical";
        String sensor_name "Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM no pressure sensor              , Seabird SBE 37-IM with pressure sensor            , Seabird SBE 37-IM with pressure sensor              ";
        String sensor_serial_number "2974, 2486, 954, 2934, 2718, 961, 2809, 3416, 1520, 3415, ";
        String ancillary_variables "PSAL_QC";
        Float64 accuracy 0.02;
        String cell_methods "Time:point DEPTH:point LATITUDE:point LONGITUDE:point";
        String DM_indicator "D";
    }
    PSAL_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        String comment "Quality Marker for each Practical PSAL Units for each nominal depth(s) of 25    38    67   107   152   252   403   603   803  1003 meter(s)";
        Int16 _FillValue -128;
        Int32 valid_min 0;
        Int32 valid_max 9;
    }
    NC_GLOBAL {
        String description "File of temperature, conductivity and pressure data collected at PAP4 mooring number 2 at 49.1192 Degrees N -16.4935 Degrees W Deployment between 22-Jun-2004 and 08-Jul-2005 09:45:00";
        String data_type "OceanSITES time-series data";
        String format_version "1.2";
        String platform_code "PAP-2";
        String date_update "2010-11-18T16:40:51Z";
        String institution "NOC";
        String site_code "PAP";
        String network "EuroSITES";
        String wmo_platform_code "62442";
        String source "Mooring observation";
        String history "Delayed-mode processed into matlab structure";
        String data_mode "D";
        Float64 quality_control_indicator 1.0;
        String quality_index "B";
        String references "http://www.eurosites.info, http://www.oceansites.org, http://www.coriolis.eu.org";
        String comment "Data processed to quarter hourly data points";
        String Conventions "OceanSITES Manual 1.2, CF-1.4";
        String Netcdf_version "3.5";
        String title "OceanSITES PAP in-situ data";
        String summary "EuroSITES European Ocean Observatory NetworkEU Framework 7 collaborative project contract FP7-ENV-2007-1-202955";
        String naming_authority "OceanSITES";
        String id "OS_PAP-2_200406_D_CTD";
        String cdm_data_type "Station";
        String area "North Atlantic Ocean";
        String geospatial_lat_min "48.5";
        String geospatial_lat_max "49.5";
        String geospatial_lon_min "-17";
        String geospatial_lon_max "-16";
        String geospatial_vertical_min "25";
        String geospatial_vertical_max "1003";
        String time_coverage_start "2004-06-22T22:00:00Z";
        String time_coverage_end "2005-07-08T09:45:00Z";
        String institution_references "http://www.noc.soton.ac.uk,http://www.ifm-geomar.de";
        String contact "redacted";
        String author "redacted";
        String data_assembly_center "EuroSITES";
        String pi_name "redacted";
        String distribution_statement "Follows CLIVAR (Climate Variability and Predictability) standards,cf. http://www.clivar.org/data/data_policy.php. Data available free of charge. User assumes all risk for use of data. User must display citation in any publication or product using data. User must contact PI prior to any commercial use of data.";
        String citation "These data were collected and made freely available by the OceanSITES project and the national programs that contribute to it.";
        String update_interval "void";
        String qc_manual "Calibration of Physical Data Microcat, TD-Logger, ADCP, RCM by Johannes Karstensen, IFM-GEOMAR, January 2005";
    }
}
