Attributes {
    LONGITUDE {
        String point_spacing "even";
        String axis "X";
        String units "degrees_east";
        String long_name "Longitude";
        String standard_name "longitude";
        String QC_procedure "5";
        String uncertainty "0.0001";
        String valid_min "-180";
        String valid_max "180";
        String modulo " ";
    }
    LATITUDE {
        String point_spacing "even";
        String axis "Y";
        String units "degrees_north";
        String long_name "Latitude";
        String standard_name "latitude";
        String QC_procedure "5";
        String uncertainty "0.0001";
        String valid_min "-90";
        String valid_max "90";
    }
    DEPTH {
        String units "METERS";
        String point_spacing "uneven";
        String axis "Z";
        String bounds "DEPTH_bnds";
        String positive "down";
        String long_name "Depth";
        String standard_name "depth";
        String QC_procedure "5";
        String uncertainty "0.1";
        String valid_min "0";
        String valid_max "5000";
    }
    DEPTH_bnds {
    }
    TIME {
        String units "DAYS since 1950-01-01 00:00:00";
        String axis "T";
        String time_origin "01-JAN-1950 00:00:00";
        String long_name "Time";
        String standard_name "time";
        String QC_procedure "1";
        String uncertainty "0.5";
        String valid_min "1086307518";
        String valid_max "1097085372";
    }
    PSAL {
        Float32 missing_value -1.0E34;
        Float32 _FillValue -1.0E34;
        String long_name "Hourly sea_water_salinity";
        String units " ";
        String standard_name "sea_water_salinity";
        String uncertainty "0.02";
        String valid_min "30";
        String valid_max "36";
        String cell_methods "time: mean";
        String history "From m0_ctd0001_20040604_original";
    }
    PSAL_QC {
        Float32 missing_value -1.0E34;
        Float32 _FillValue -1.0E34;
        String long_name "quality flag";
        String units " ";
        String conventions "OceanSITES reference table 2";
        String history "From m0_ctd0001_20040604_original";
    }
    TEMP {
        Float32 missing_value -1.0E34;
        Float32 _FillValue -1.0E34;
        String long_name "Hourly sea_water_temperature";
        String units "celsius";
        String standard_name "sea_water_temperature";
        String uncertainty "0.002";
        String valid_min "0";
        String valid_max "35";
        String cell_methods "time: mean";
        String history "From m0_ctd0001_20040604_original";
    }
    TEMP_QC {
        Float32 missing_value -1.0E34;
        Float32 _FillValue -1.0E34;
        String long_name "quality flag";
        String units " ";
        String conventions "OceanSITES reference table 2";
        String history "From m0_ctd0001_20040604_original";
    }
    TIME_QC {
        Float32 missing_value -1.0E34;
        Float32 _FillValue -1.0E34;
        String long_name "Quality flag for time axis, 1: Good data";
    }
    POSITION_QC {
        Float32 missing_value -1.0E34;
        Float32 _FillValue -1.0E34;
        String long_name "Quality flag for Latitude and Longitude axes, 1: Good data";
    }
    DEPTH_QC {
        Float32 missing_value -1.0E34;
        Float32 _FillValue -1.0E34;
        String long_name "Quality flag for depth axis, 1: Good data";
    }
    NC_GLOBAL {
        String title "Hourly Gridded MBARI Mooring M0 Sea Water Temperature and Salinity Observations";
        String summary "These data have been processed from the original instrument netCDF files which have individual irregular time axes.  The data in this file have been combined on a common hourly time axes and a common nominal depth axis.  Data values outside of reasonable ranges have been flagged as bad.";
        String keywords "CTD, Sea Water Temperature, Sea Water Salinity, Monterey Bay, OASIS, CIMT, MSE, MOOS";
        String standard_name_vocabulary "CF-1.1";
        String id "/mbari/ssdsdata/deployments/m0/200406/OS_MBARI-M0_20040604_R_TS.nc";
        String naming_authority "OceanSITES";
        String keywords_vocabulary "GCMD Science Keywords";
        String cdm_data_type "Station";
        String creator_name "redacted";
        String project "SSDS";
        String data_type "OceanSITES time-series data";
        String format_version "1.2";
        String platform_code "MBARI-M0";
        String wmo_platform_code "46091";
        String date_created "2010-09-29T18:40:49Z";
        String date_update "2010-09-29T18:40:49Z";
        String site_code "MBARI";
        String institution "Monterey Bay Aquarium Research Institute";
        String data_mode "R";
        String quality_control_indicator "1";
        String quality_index "B";
        String netcdf_version "3.5";
        String area "North Pacific Ocean";
        String institution_references "http://www.mbari.org/oasis";
        String contact "redacted";
        String author "redacted";
        String data_assembly_center "MBARI";
        String pi_name "redacted";
        String distribution_statement "Follows CLIVAR (Climate Varibility and Predictability)  standards, cf. http://www.clivar.org/data/data_policy.php. Data available free of charge. User assumes all risk for use of data. User must display citation in any publication or product using data. User must contact PI prior to any commercial use of data.";
        String citation "These data were collected and made freely available by the Monterey Bay Aquarium Research Institute.";
        String update_interval "void";
        String qc_manual "http://www.oceansites.org/data/quality_control_manual.pdf";
        String geospatial_lat_min "36.833333";
        String geospatial_lat_max "36.833333";
        String geospatial_lon_min "-121.903333";
        String geospatial_lon_max "-121.903333";
        String geospatial_vertical_min "1";
        String geospatial_vertical_max "55";
        String geospatial_vertical_positive "down";
        String time_coverage_start "2004-06-04T00:00:00Z";
        String time_coverage_end "2004-10-06T17:00:00Z";
        String source "Mooring Observation";
        String program "combineTS.pl -mooring M0 -ssdsServer new-ssds.mbari.org -deployments 200406 -ssdsDataServer new-ssds.mbari.org -inputDir /mbari/ssdsdata/deployments";
        String version "1.59";
        String user "ssdsadmin";
        String host "elvis.shore.mbari.org";
        String created "Wed Sep 29 11:40:49 2010";
        String history "FERRET V6.62   29-Sep-10";
        String Conventions "CF-1.0";
        String ssds_provenance "DC.name=OS_MBARI-M0_20040604_R_TS.nc<br>DC.dataContainerType=File<br>DC.original=false<br>DC.uriString=http://dods.mbari.org/opendap/data/ssdsdata/deployments/m0/200406/OS_MBARI-M0_20040604_R_TS.nc<br>DC.dodsAccessible=true<br>DC.dodsUrlString=http://dods.mbari.org/opendap/data/ssdsdata/deployments/m0/200406/OS_MBARI-M0_20040604_R_TS.nc<br>DC.noNetCDF=true<br>+DP.name=combineTS.pl run on 2010-09-29T18:40:49Z<br>+DP.description=combineTS.pl script executed with arguments: -mooring M0 -ssdsServer new-ssds.mbari.org -deployments 200406 -ssdsDataServer new-ssds.mbari.org -inputDir /mbari/ssdsdata/deployments<br>+DP.dataProducerType=ProcessRun<br>+DP.startDate=2010-09-29T18:40:49Z<br>+DP.endDate=2010-09-29T18:40:54Z<br>+DP.hostName=elvis.shore.mbari.org<br>+Software.name=combineTS.pl<br>+Software.description=Examine all CTD instrument netCDF files for this mooring deployment, construct a Ferret .jnl file that grids and combines all the data to common time and vertical axes.
<br>+Software.uriString=http://moonjelly.shore.mbari.org/cgi-bin/cvsweb.cgi/DPforSSDS/cimt/combineTS.pl?rev=1.59<br>+Software.softwareVersion=1.59<br>.+DC.name=m0_ctd0001_20040604_original.nc<br>.+DC.dataContainerType=File<br>.+DC.original=false<br>.+DC.uriString=http://dods.mbari.org/opendap/data/ssdsdata/deployments/m0/200406/m0_ctd0001_20040604_original.nc<br>.+DC.dodsAccessible=false<br>.+DC.dodsUrlString=http://dods.mbari.org/opendap/data/ssdsdata/deployments/m0/200406/m0_ctd0001_20040604_original.nc<br>.+DC.noNetCDF=true<br>..+DP.name=DStoNetCDF.pl - ctd.pl run on 2010-09-29T18:35:35Z<br>..+DP.description=DStoNetCDF.pl script executed with arguments: -mooring M0 -deployment M0 - June 2004 -ssdsServer new-ssds.mbari.org -ssdsDataServer new-ssds.mbari.org -outputDir /mbari/ssdsdata/deployments -procClosed -verbose<br>..+DP.dataProducerType=ProcessRun<br>..+DP.startDate=2010-09-29T18:35:35Z<br>..+DP.endDate=2010-09-29T18:35:42Z<br>..+DP.hostName=elvis<br>..+Software.name=ctd.pl<br>..+Software.description=Salinity is calculated from C, T, and P using conductivity ratio divisor of 4.29140.<br>..+Software.uriString=http://moonjelly.shore.mbari.org/cgi-bin/cvsweb.cgi/DPforSSDS/cimt/ctd.pl?rev=1.52<br>..+Software.softwareVersion=1.52<br>...+DC.name=m0_ctd0001_20040727_original.nc<br>...+DC.dataContainerType=File<br>...+DC.original=false<br>...+DC.uriString=http://dods.mbari.org/opendap/data/ssdsdata/deployments/m0/200406/m0_ctd0001_20040727_original.nc<br>...+DC.dodsAccessible=false<br>...+DC.dodsUrlString=http://dods.mbari.org/opendap/data/ssdsdata/deployments/m0/200406/m0_ctd0001_20040727_original.nc<br>...+DC.noNetCDF=true<br>....+DP.name=DStoNetCDF.pl - ctd.pl run on 2010-09-29T18:40:21Z<br>....+DP.description=DStoNetCDF.pl script executed with arguments: -mooring M0 -deployment M0 - June 2004 -ssdsServer new-ssds.mbari.org -ssdsDataServer new-ssds.mbari.org -outputDir /mbari/ssdsdata/deployments -procClosed -verbose<br>....+DP.dataProducerType=ProcessRun<br>....+DP.startDate=2010-09-29T18:40:21Z<br>....+DP.endDate=2010-09-29T18:40:28Z<br>....+DP.hostName=elvis<br>....+Software.name=ctd.pl<br>....+Software.description=Salinity is calculated from C, T, and P using conductivity ratio divisor of 4.29140.<br>....+Software.uriString=http://moonjelly.shore.mbari.org/cgi-bin/cvsweb.cgi/DPforSSDS/cimt/ctd.pl?rev=1.52<br>....+Software.softwareVersion=1.52<br>.....+DC.name=m0_imctd_20040604_original.nc<br>.....+DC.dataContainerType=File<br>.....+DC.original=false<br>.....+DC.uriString=http://dods.mbari.org/opendap/data/ssdsdata/deployments/m0/200406/m0_imctd_20040604_original.nc<br>.....+DC.dodsAccessible=false<br>.....+DC.dodsUrlString=http://dods.mbari.org/opendap/data/ssdsdata/deployments/m0/200406/m0_imctd_20040604_original.nc<br>.....+DC.noNetCDF=true<br>......+DP.name=DStoNetCDF.pl - imctd.pl run on 2010-09-29T18:35:56Z<br>......+DP.description=DStoNetCDF.pl script executed with arguments: -mooring M0 -deployment M0 - June 2004 -ssdsServer new-ssds.mbari.org -ssdsDataServer new-ssds.mbari.org -outputDir /mbari/ssdsdata/deployments -procClosed -verbose<br>......+DP.dataProducerType=ProcessRun<br>......+DP.startDate=2010-09-29T18:35:56Z<br>......+DP.endDate=2010-09-29T18:36:01Z<br>......+DP.hostName=elvis<br>......+Software.name=imctd.pl<br>......+Software.description=Read inductive modem instrument data stream and produce NetCDF file of those data.There is an independent time axis for each microcat.  The time of sample is parsed from text of timestamp for each record. <br>......+Software.uriString=http://moonjelly.shore.mbari.org/cgi-bin/cvsweb.cgi/DPforSSDS/cimt/imctd.pl?rev=1.41<br>......+Software.softwareVersion=1.41<br>.......+DC.name=1319_1_1_1299<br>.......+DC.dataContainerType=Stream<br>.......+DC.original=false<br>.......+DC.uriString=http://new-ssds.mbari.org:8080/servlet/GetOriginalDataServlet?deviceID=1319&startParentID=1299&startPacketSubType=1&startDataDescriptionID=1&lastNumberOfPackets=10&isi=1<br>.......+DC.dodsAccessible=false<br>.......+DC.noNetCDF=true<br>........+DP.name=ID 1319 deployed on id 1299<br>........+DP.dataProducerType=Deployment<br>........+DP.startDate=2004-06-04T00:00:00Z<br>........+DP.endDate=2004-10-06T18:00:00Z<br>........+DP.role=instrument<br>.........+Device.uuid=F8866D9E-602E-4F01-8393-3F0734127BB1<br>.........+Device.name=Inductive CTD Modem<br>.........+Device.description=Communication device/reporting instrument for an inductive CTD string (1st deployed on M0-CIMT)<br>.........+Device.mfgName=Seabird<br>.........+Device.mfgModel=S-MODEM1<br>.........+Device.mfgSerialNumber=0278<br>.........+DP.name=CTD at 10m<br>.........+DP.dataProducerType=Deployment<br>.........+DP.startDate=2004-06-04T00:00:00Z<br>.........+DP.endDate=2004-10-06T18:00:00Z<br>.........+DP.role=sensor<br>.........+DP.nominalDepth=10.0<br>.........+Device.uuid=f6763d9c-d50f-11d9-8c1e-00306e389969<br>.........+Device.name=Inductive CTD<br>.........+Device.mfgName=Seabird<br>.........+Device.mfgModel=SVE37IMP<br>.........+Device.mfgSerialNumber=37IM20000-3532<br>.........+DP.name=CTD at 20m<br>.........+DP.dataProducerType=Deployment<br>.........+DP.startDate=2004-06-04T00:00:00Z<br>.........+DP.endDate=2004-10-06T18:00:00Z<br>.........+DP.role=sensor<br>.........+DP.nominalDepth=20.0<br>.........+Device.uuid=f6a8712d-d50f-11d9-8c1e-00306e389969<br>.........+Device.name=Inductive CTD<br>.........+Device.mfgName=Seabird<br>.........+Device.mfgModel=SVE37IMP<br>.........+Device.mfgSerialNumber=37IM20000-3533<br>.........+DP.name=CTD at 40m<br>.........+DP.dataProducerType=Deployment<br>.........+DP.startDate=2004-06-04T00:00:00Z<br>.........+DP.endDate=2004-10-06T18:00:00Z<br>.........+DP.role=sensor<br>.........+DP.nominalDepth=40.0<br>.........+Device.uuid=f6b0606e-d50f-11d9-8c1e-00306e389969<br>.........+Device.name=Inductive CTD<br>.........+Device.mfgName=Seabird<br>.........+Device.mfgModel=SVE37IMP<br>.........+Device.mfgSerialNumber=37IM20000-3534<br>.........+DP.name=CTD at 55m<br>.........+DP.dataProducerType=Deployment<br>.........+DP.startDate=2004-06-04T00:00:00Z<br>.........+DP.endDate=2004-10-06T18:00:00Z<br>.........+DP.role=sensor<br>.........+DP.nominalDepth=55.0<br>.........+Device.uuid=f6b78c5f-d50f-11d9-8c1e-00306e389969<br>.........+Device.name=Inductive CTD<br>.........+Device.mfgName=Seabird<br>.........+Device.mfgModel=SVE37IMP<br>.........+Device.mfgSerialNumber=37IM20000-3535<br>";
    }
    DODS_EXTRA {
        String Unlimited_Dimension "TIME";
    }
}
