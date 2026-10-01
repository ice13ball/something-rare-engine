Attributes {
    TIME {
        Float64 _FillValue 999999.0;
        String long_name "time";
        String standard_name "time";
        String units "days since 1950-01-01T00:00:00Z";
        Float64 valid_min 0.0;
        Float64 valid_max 90000.0;
        Int32 QC_indicator 7;
        Int32 QC_procedure 5;
        Float64 uncertainty 0.0417;
        String axis "T";
    }
    LATITUDE {
        Float32 _FillValue 99999.0;
        String long_name "Latitude of each location";
        String standard_name "latitude";
        String units "degrees_north";
        Float64 valid_min -90.0;
        Float64 valid_max 90.0;
        Int32 QC_indicator 7;
        Int32 QC_procedure 5;
        Float64 uncertainty 0.0045;
        String axis "Y";
        String reference "WGS84";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::4326";
    }
    LONGITUDE {
        Float32 _FillValue 99999.0;
        String long_name "Longitude of each location";
        String standard_name "longitude";
        String units "degrees_east";
        Float64 valid_min -180.0;
        Float64 valid_max 180.0;
        Int32 QC_indicator 7;
        Int32 QC_procedure 5;
        Float64 uncertainty 0.004644469743585655;
        String axis "X";
        String reference "WGS84";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::4326";
    }
    DEPTH {
        Float32 _FillValue -99999.0;
        String long_name "Depth of each measurement";
        String standard_name "depth";
        String units "meters";
        Float64 valid_min 0.0;
        Float64 valid_max 12000.0;
        Int32 QC_indicator 8;
        Int32 QC_procedure 2;
        Float64 uncertainty 1.0;
        String positive "down";
        String axis "Z";
        String reference "sea_level";
        String coordinate_reference_frame "urn:ogc:crs:EPSG::5113";
    }
    TEMP {
        Float64 _FillValue 99999.0;
        String long_name "sea water temperature";
        String standard_name "sea_water_temperature";
        String units "degree_Celsius";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 valid_min -2.0;
        Float64 valid_max 35.0;
        Float64 sensor_depth 999.0;
        Float64 uncertainty 0.002;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "TEMP_QC";
    }
    TEMP_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    PSAL1 {
        Float64 _FillValue 99999.0;
        String long_name "ctd salinity";
        String standard_name "sea_water_practical_salinity";
        String units "pss-78";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 valid_min 0.0;
        Float64 valid_max 42.0;
        Float64 sensor_depth 999.0;
        Float64 uncertainty 0.005;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "PSAL1_QC";
    }
    PSAL1_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    PSAL {
        Float64 _FillValue 99999.0;
        String long_name "sea water salinity";
        String standard_name "sea_water_salinity";
        String units "psu";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 valid_min 0.0;
        Float64 valid_max 42.0;
        Float64 sensor_depth 999.0;
        Float64 uncertainty 0.005;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "PSAL_QC";
    }
    PSAL_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    DOXY1 {
        Float64 _FillValue 99999.0;
        String long_name "oxygen";
        String standard_name "mole_concentration_of_dissolved_molecular_oxygen_in_sea_water";
        String units "micromole/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 valid_min 0.0;
        Float64 valid_max 500.0;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "DOXY1_QC";
    }
    DOXY1_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    SILC1 {
        Float64 _FillValue 99999.0;
        String long_name "silicate";
        String standard_name "mole_concentration_of_silicate_in_sea_water";
        String units "umol/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 valid_min 0.0;
        Float64 valid_max 250.0;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "SILC1_QC";
    }
    SILC1_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    NO21 {
        Float64 _FillValue 99999.0;
        String long_name "nitrite";
        String standard_name "mole_concentration_of_nitrite_in_sea_water";
        String units "umol/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 valid_min -0.1;
        Float64 valid_max 15.0;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "NO21_QC";
    }
    NO21_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    PO41 {
        Float64 _FillValue 99999.0;
        String long_name "phosphate";
        String standard_name "mole_concentration_of_phosphate_in_sea_water";
        String units "umol/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 valid_min 0.0;
        Float64 valid_max 5.0;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "PO41_QC";
    }
    PO41_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    ALK {
        Float64 _FillValue 99999.0;
        String long_name "alkalinity";
        String standard_name "sea_water_alkalinity_expressed_as_mole_equivalent";
        String units "uequiv";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 valid_min 100.0;
        Float64 valid_max 2800.0;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "ALK_QC";
    }
    ALK_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    CORG {
        Float64 _FillValue 99999.0;
        String long_name "particulate organic carbon";
        String standard_name "WC_POC";
        String units "ug/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "CORG_QC";
    }
    CORG_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    TDNT {
        Float64 _FillValue 99999.0;
        String long_name "total organic nitrogen";
        String standard_name "WC_DissNitrogen";
        String units "umol/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "TDNT_QC";
    }
    TDNT_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    TDNT1 {
        Float64 _FillValue 99999.0;
        String long_name "dissolved organic nitrogen";
        String standard_name "WC_DissNitrogen";
        String units "umol/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 valid_min 200.0;
        Float64 valid_max 900.0;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
    }
    NTOT {
        Float64 _FillValue 99999.0;
        String long_name "particulate organic nitrogen";
        String standard_name "WC_PON";
        String units "ug/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "NTOT_QC";
    }
    NTOT_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    BATX {
        Float64 _FillValue 99999.0;
        String long_name "bacteria enumeration";
        String standard_name "BactTaxaAbundWater";
        String units "cells*10^8/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "BATX_QC";
    }
    BATX_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    NO31 {
        Float64 _FillValue 99999.0;
        String long_name "nitrate + nitrite";
        String standard_name "mole_concentration_of_nitrate_and_nitrite_in_sea_water";
        String units "umol/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 valid_min -0.1;
        Float64 valid_max 47.0;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "NO31_QC";
    }
    NO31_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    POP {
        Float64 _FillValue 99999.0;
        String long_name "pop";
        String standard_name "mole_concentration_of_particulate_organic_matter_expressed_as_phosphorus_in_sea_water";
        String units "umol/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "POP_QC";
    }
    POP_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    SIGTH {
        Float64 _FillValue 99999.0;
        String long_name "sigma theta";
        String standard_name "sea_water_sigma_theta";
        String units "kg/m^3";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "SIGTH_QC";
    }
    SIGTH_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    CO2 {
        Float64 _FillValue 99999.0;
        String long_name "dissolved inorganic carbon";
        String standard_name "mole_concentration_of_dissolved_inorganic_carbon_in_sea_water";
        String units "umol/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "CO2_QC";
    }
    CO2_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    DOXY_TEMP {
        Float64 _FillValue 99999.0;
        String long_name "oxygen fix temperature";
        String standard_name "temperature_of_sensor_for_oxygen_in_sea_water";
        String units "degree_Celsius";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "DOXY_TEMP_QC";
    }
    DOXY_TEMP_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    TDPX {
        Float64 _FillValue 99999.0;
        String long_name "total dissolved phosphorus";
        String standard_name "WC_DissPhosphorus";
        String units "nmol/kg";
        Int32 QC_indicator 2;
        Int32 QC_procedure 5;
        Float64 sensor_depth 999.0;
        Float64 uncertainty Infinity;
        String cell_methods "TIME: point DEPTH: average LATITUDE: point LONGITUDE: point";
        String DM_indicator "D";
        String ancillary_variables "TDPX_QC";
    }
    TDPX_QC {
        String _Unsigned "false";
        Int16 _FillValue -128;
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int32 valid_min 0;
        Int32 valid_max 9;
        Int32 flag_values 0, 1, 2, 3, 4, 5, 6, 7, 8, 9;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed not_used nominal_value interpolated_value missing_value";
    }
    NC_GLOBAL {
        String data_type "OceanSITES time-series BTL data";
        String format_version "1.2";
        String wmo_platform_code "";
        String platform_code "BATS-1";
        String date_update "2013-03-01T20:58:22.758281Z";
        String source "Shipborne observation";
        String history "2011-05-17T18:50:00Z data collected
2013-03-01T20:58:22.758281Z date file translated/written";
        String data_mode "D";
        String quality_control_indicator "1";
        String quality_index "B";
        String Conventions "CF-1.4, OceanSITES 1.1";
        String netcdf_version "3.x";
        String naming_authority "OceanSITES";
        String cdm_data_type "Station";
        String geospatial_lat_min "31.666";
        String geospatial_lat_max "31.666";
        String geospatial_lon_min "-64.162";
        String geospatial_lon_max "-64.162";
        Int32 geospatial_vertical_min 0;
        String geospatial_vertical_max "4200.8";
        String geospatial_vertical_positive "down";
        String author "redacted";
        String data_assembly_center "CCHDO";
        String distribution_statement "Follows CLIVAR (Climate Varibility and Predictability) standards, cf.
http://www.clivar.org/data/data_policy.php.  Data available free of charge. User
assumes all risk for use of data. User must display citation in any publication
or product using data. User must contact PI prior to any commercial use of
data.";
        String citation "These data were collected and made freely available by the OceanSITES project
and the national programs that contribute to it.";
        String update_interval "void";
        String qc_manual "http://www.ocensites.org/data/quality_control_manual.pdf";
        String time_coverage_start "2011-05-17T18:50:00Z";
        String time_coverage_end "2011-05-17T18:50:00Z";
        String institution "Bermuda Institute of Ocean Sciences";
        String institution_references "http://bats.bios.edu/";
        String site_code "BATS";
        String array "BERMUDA";
        String references "http://cchdo.ucsd.edu/search?query=group:BATS";
        String comment "BIOS-BATS BTL data from SIO, translated to OceanSITES NetCDF by SIO";
        String summary "BIOS-BATS BTL data Bermuda";
        String area "Atlantic - Sargasso Sea";
        String contact "redacted";
        String pi_name "redacted";
        String title "BATS BTL Timeseries ExpoCode=33H420110517 Station=BATSCR Cast=4";
        String id "OS_BATS-1_BATSCR-0269-4_D_BTL";
    }
    DODS_EXTRA {
        String Unlimited_Dimension "TIME";
    }
    EXTRA_DIMENSION {
        Int32 POSITION 1;
    }
}
