Attributes {
    TIME {
        String long_name "time";
        String standard_name "time";
        String units "days since 1950-01-01T00:00:00Z";
        String valid_min "1983-04-19T18:00:00Z";
        String valid_max "1983-10-19T08:00:00Z";
        Float64 QC_indicator 1.0;
        Float64 QC_procedure 6.0;
        String comments "RCM4/5 time from instrument's manually logged start & stop times, and from instrument's recording interval.// RCM7/8 time from instrument's manually logged start & stop time, and from daily internal time records.// ";
        String axis "T";
    }
    LATITUDE {
        String long_name "Latitude of each location";
        String standard_name "latitude";
        String units "degrees_north";
        Float64 valid_min 33.177;
        Float64 valid_max 33.177;
        Float64 QC_indicator 1.0;
        Float64 QC_procedure 6.0;
        Float64 uncertainty 0.010416666666666666;
        String comments "Mooring launched 'buoy first'.// Mooring position estimated as 1/3 mooring length from ship's position when slipping anchor directed to top buoy.// Ship's position: until availibility of GPS, dead reckoning incl. transit satellite navigation// ";
        String axis "Y";
        String reference "WGS84";
    }
    LONGITUDE {
        String long_name "Longitude of each location";
        String standard_name "longitude";
        String units "degrees_east";
        Float64 valid_min -21.917;
        Float64 valid_max -21.917;
        Float64 QC_indicator 1.0;
        Float64 QC_procedure 6.0;
        Float64 uncertainty 0.012445478073067761;
        String comments "Mooring launched 'buoy first'.// Mooring position estimated as 1/3 mooring length from ship's position when slipping anchor directed to top buoy.// Ship's position: until availibility of GPS, dead reckoning incl. transit satellite navigation// ";
        String axis "X";
        String reference "WGS84";
    }
    DEPTH {
        String long_name "Depth of each measurement";
        String standard_name "depth";
        String units "meters";
        String positive "down";
        Float32 _FillValue -9999.0;
        Float64 valid_min 0.0;
        Float64 valid_max 5500.0;
        Float64 QC_indicator 1.0;
        Float64 QC_procedure 6.0;
        String uncertainty "20 m";
        String comment "Depths from  deployment logs, static mooring model and comparison of RCMs' 1st day median data with deployment CTD.// Depths represent initial best estimates, but may vary with time and mooring motion.// Resulting depths are initial best estimates; see Mueller & Waniek (2013):  DOI 10.3289/GEOMAR_REP_NS_13_2013.// ";
        String axis "Z";
        String reference "mean_sea_level";
    }
    PRES {
        String long_name "sea water pressure";
        String standard_name "sea_water_pressure";
        String units "dbar";
        Float32 _FillValue -9999.0;
        Float64 QC_procedure 6.0;
        Float64 valid_min 0.0;
        Float64 valid_max 6300.0;
        String comment "Running median de-spiker over 9 records & visual control; spikes replaced by median; non-correctable values replaced by FILL_VALUE.// Pressure values offset corrected to initially meet estimated instrument depth.// For details see Mueller & Waniek (2013):  DOI 10.3289/GEOMAR_REP_NS_13_2013.// ";
        Float64 sensor_depth 239.0, 473.0, 677.0, 1081.0, 1587.0, 3013.0, 5237.0;
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "Aanderaa RCM  Models 4, 5, 7 & 8; see Aanderaa Rep. 1990. Oper. Man. Recording Current Meter models 7&8. Techn. Descr. No. 159, Aanderaa Instruments, Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.";
        String sensor_vendor "Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.";
        String sensor_serial_number "//  RCM4 S/N 776//  RCM4 S/N 1407//  RCM4 S/N 1409//  RCM4 S/N 2025//  RCM5 S/N 4352//  RCM5 S/N 4565//  RCM5 S/N 5327// ";
        String ancillary_variables "PRES_QC";
        Float64 accuracy 12.0;
        Float64 resolution 6.0;
        Float64 precision 6.0;
        String cell_methods "point";
    }
    PRES_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int16 _FillValue -128;
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Float64 flag_values 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 8.0, 9.0;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed nominal_value interpolated_value missing_value";
    }
    UCUR {
        String long_name "eastward sea water velocity";
        String standard_name "eastward_sea_water_velocity";
        String units "cm/s";
        Float32 _FillValue -9999.0;
        Float64 QC_procedure 5.0;
        Float64 valid_min -300.0;
        Float64 valid_max 300.0;
        String comment "UCUR and VCUR are East and North componets of current, derived from speed and direction data.// Single speed minimum measurement is ca 1.2 cm/s; single direction compss dead angle is -2� to 2�.// RCM4/5 data: speed stored as integral over recording interval; direction is single mesaurement at the end of recording interval.// RCM7/8 data: quasi vector averaged data stored, see Aanderaa RCM  Models 4, 5, 7 & 8; see Aanderaa Rep. 1990. Oper. Man. Recording Current Meter models 7&8. Techn. Descr. No. 159, Aanderaa Instruments, Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.// Running median de-spiker over 9 records & visual control; spikes replaced by median; non-correctable values replaced by FILL_VALUE.// For details see Mueller & Waniek (2013):  DOI 10.3289/GEOMAR_REP_NS_13_2013.// ";
        Float64 sensor_depth 239.0, 473.0, 677.0, 1081.0, 1587.0, 3013.0, 5237.0;
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "Aanderaa RCM  Models 4, 5, 7 & 8; see Aanderaa Rep. 1990. Oper. Man. Recording Current Meter models 7&8. Techn. Descr. No. 159, Aanderaa Instruments, Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.";
        String sensor_vendor "Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.";
        String sensor_serial_number "//  RCM4 S/N 776//  RCM4 S/N 1407//  RCM4 S/N 1409//  RCM4 S/N 2025//  RCM5 S/N 4352//  RCM5 S/N 4565//  RCM5 S/N 5327// ";
        String ancillary_variables "UCUR_QC";
        Float64 accuracy 1.0;
        Float64 resolution 0.3;
        Float64 precision 0.6;
        String cell_methods "point";
    }
    UCUR_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int16 _FillValue -128;
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Float64 flag_values 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 8.0, 9.0;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed nominal_value interpolated_value missing_value";
    }
    VCUR {
        String long_name "northward sea water velocity";
        String standard_name "northward_sea_water_velocity";
        String units "cm/s";
        Float32 _FillValue -9999.0;
        Float64 QC_indicator 1.0;
        Float64 QC_procedure 5.0;
        Float64 valid_min -300.0;
        Float64 valid_max 300.0;
        String comment "UCUR and VCUR are East and North componets of current, derived from speed and direction data.// Single speed minimum measurement is ca 1.2 cm/s; single direction compss dead angle is -2� to 2�.// RCM4/5 data: speed stored as integral over recording interval; direction is single mesaurement at the end of recording interval.// RCM7/8 data: quasi vector averaged data stored, see Aanderaa RCM  Models 4, 5, 7 & 8; see Aanderaa Rep. 1990. Oper. Man. Recording Current Meter models 7&8. Techn. Descr. No. 159, Aanderaa Instruments, Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.// Running median de-spiker over 9 records & visual control; spikes replaced by median; non-correctable values replaced by FILL_VALUE.// For details see Mueller & Waniek (2013):  DOI 10.3289/GEOMAR_REP_NS_13_2013.// ";
        Float64 sensor_depth 239.0, 473.0, 677.0, 1081.0, 1587.0, 3013.0, 5237.0;
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "Aanderaa RCM  Models 4, 5, 7 & 8; see Aanderaa Rep. 1990. Oper. Man. Recording Current Meter models 7&8. Techn. Descr. No. 159, Aanderaa Instruments, Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.";
        String sensor_vendor "Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.";
        String sensor_serial_number "//  RCM4 S/N 776//  RCM4 S/N 1407//  RCM4 S/N 1409//  RCM4 S/N 2025//  RCM5 S/N 4352//  RCM5 S/N 4565//  RCM5 S/N 5327// ";
        String ancillary_variables "UCUR_QC";
        Float64 accuracy 1.0;
        Float64 resolution 0.3;
        Float64 precision 0.6;
        String cell_methods "point";
    }
    VCUR_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int16 _FillValue -128;
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Float64 flag_values 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 8.0, 9.0;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed nominal_value interpolated_value missing_value";
    }
    TEMP {
        String long_name "sea water temperature";
        String standard_name "sea_water_temperature";
        String units "degree_Celsius";
        Float32 _FillValue -9999.0;
        Float64 QC_procedure 5.0;
        Float64 valid_min -2.0;
        Float64 valid_max 32.0;
        String comment "TEMP as measured & converted by Aanderaa RCM standard or lab calibration coefficients.// Running median de-spiker over 9 records & visual control; spikes replaced by median; non-correctable values replaced by FILL_VALUE.// Offset corrections Tcorr to match deployment CTD if available;// Tcorr applied in two cases: (i) z>2000 m; (ii) z<2000m & abs(Tcorr)>0.45 K.// Deep ocean (>2000 m) temperature may need further correction.// For details see Mueller & Waniek (2013):  DOI 10.3289/GEOMAR_REP_NS_13_2013// ";
        Float64 sensor_depth 239.0, 473.0, 677.0, 1081.0, 1587.0, 3013.0, 5237.0;
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "Aanderaa RCM  Models 4, 5, 7 & 8; see Aanderaa Rep. 1990. Oper. Man. Recording Current Meter models 7&8. Techn. Descr. No. 159, Aanderaa Instruments, Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.";
        String sensor_vendor "Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.";
        String sensor_serial_number "//  RCM4 S/N 776//  RCM4 S/N 1407//  RCM4 S/N 1409//  RCM4 S/N 2025//  RCM5 S/N 4352//  RCM5 S/N 4565//  RCM5 S/N 5327// ";
        String ancillary_variables "TEMP_QC";
        Float64 accuracy 0.1;
        Float64 resolution 0.03;
        Float64 precision 0.06;
        String cell_methods "point";
    }
    TEMP_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int16 _FillValue -128;
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Float64 flag_values 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 8.0, 9.0;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed nominal_value interpolated_value missing_value";
    }
    PSAL {
        String long_name "sea water salinity";
        String standard_name "sea_water_salinity";
        String units "IPSS78 scale";
        Float32 _FillValue -9999.0;
        Float64 QC_procedure 5.0;
        Float64 valid_min 0.0;
        Float64 valid_max 37.0;
        String comment "Salinity is IPSS78 practical_salinity(P, T, C);// here P=press80(instrument_depth,latitude),T temperature, C conductivity.// Nonlinear conductivity sensor drift may have occurred.// Running median de-spiker over 9 records & visual control; spikes replaced by median; non-correctable values replaced by FILL_VALUE.// For details see Mueller & Waniek (2013):  DOI 10.3289/GEOMAR_REP_NS_13_2013// ";
        Float64 sensor_depth 239.0, 473.0, 677.0, 1081.0, 1587.0, 3013.0, 5237.0;
        String sensor_mount "mounted_on_mooring_line";
        String sensor_name "Aanderaa RCM  Models 4, 5, 7 & 8; see Aanderaa Rep. 1990. Oper. Man. Recording Current Meter models 7&8. Techn. Descr. No. 159, Aanderaa Instruments, Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.";
        String sensor_vendor "Aanderaa Instruments, Fanaveien 13B, Bergen, Norway.";
        String sensor_serial_number "//  RCM4 S/N 776//  RCM4 S/N 1407//  RCM4 S/N 1409//  RCM4 S/N 2025//  RCM5 S/N 4352//  RCM5 S/N 4565//  RCM5 S/N 5327// ";
        String ancillary_variables "PSAL_QC";
        String accuracy "unknown";
        Float64 resolution 0.1;
        String precision "unknown";
        String cell_methods "point";
    }
    PSAL_QC {
        String _Unsigned "false";
        String long_name "quality flag";
        String conventions "OceanSITES reference table 2";
        Int16 _FillValue -128;
        Float64 valid_min 0.0;
        Float64 valid_max 9.0;
        Float64 flag_values 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 7.0, 8.0, 9.0;
        String flag_meanings "no_qc_performed good_data probably_good_data bad_data_that_are_potentially_correctable bad_data value_changed nominal_value interpolated_value missing_value";
    }
    NC_GLOBAL {
        String data_type "OceanSITES time-series data";
        String Conventions "OceanSITES-1.2,";
        String format_version "1.2";
        String platform_code "K276";
        String date_update "2016-05-27T12:07:02Z";
        String institution " IfM Kiel, Germany";
        String site_code "K276";
        String array "NEA";
        String network "KIEL276";
        Float64 wmo_platform_code 18478.0;
        String source "Mooring Observation";
        String history "redacted";
        String data_mode "D";
        String quality_control_indicator "5, Mueller & Waniek (2013) : DOI 10.3289/GEOMAR_REP_NS_13_2013";
        String quality_index "A";
        String references "http://www.oceansites.org";
        String comment "Data at highest available data rate; Data_Rate/h=1";
        String netcdf_version "3";
        String title "Physical data from moored Aanderaa Recording Current Meters (RCM), site K276";
        String summary "Oceanographic mooring data from site K276 collected in the Subtropical North Atlantic. Measured properties: temperature, currents, pressure, salinity.";
        String naming_authority "OceanSITES";
        String id "OS_K276_19830419_D_mooring27604rcm.nc";
        String cdm_data_type "Station";
        String area "Northeast Atlantic Ocean";
        Float64 geospatial_lat_min 33.177;
        Float64 geospatial_lat_max 33.177;
        Float64 geospatial_lon_min -21.917;
        Float64 geospatial_lon_max -21.917;
        Float64 geospatial_vertical_min 239.0;
        Float64 geospatial_vertical_max 5237.0;
        String time_coverage_start "1983-04-19T18:00:00Z";
        String time_coverage_end "1983-10-19T08:00:00Z";
        String institution_references "IO Warnemuende, Germany";
        String contact "redacted";
        String author "redacted";
        String data_assembly_center "GEOMAR, Kiel, Germany";
        String pi_name "redacted";
        String distribution_statement "Data available free of charge for scientific use. User must display citation in any publication or product using data and contact person named under 'contact'.";
        String citation "Mueller & Waniek (2013): DOI 10.3289/GEOMAR_REP_NS_13_2013.// Data made availabe by the OceanSITES project and the national programs that contribute to it.// ";
        String update_interval "void";
        String qc_manual "http://www.oceansites.org/docs/oceansites_user_manual_version1.2.pdf";
    }
    EXTRA_DIMENSION {
        Int32 POSITION 1;
    }
}
