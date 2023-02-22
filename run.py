import os
import shutil  # must be imported before GDAL
import glob
from glob import glob
import geopandas as gpd
from zipfile import ZipFile
import rasterio
from rasterio import features
import numpy as np
from shapely.validation import make_valid
from shapely.validation import explain_validity
from os import listdir, getenv, mkdir, remove, walk

import random
import string
import logging
from pathlib import Path
from os.path import isfile, join, isdir

# Set up paths
data_path = os.getenv('DATA_PATH', '/data')
inputs_path = os.path.join(data_path, 'inputs')
outputs_path = os.path.join(data_path, 'outputs')
if not os.path.exists(outputs_path):
    os.mkdir(outputs_path)
outputs_buildings_path=os.path.join(outputs_path,'buildings')
if not os.path.exists(outputs_buildings_path):
    os.mkdir(outputs_buildings_path)
outputs_greenareas_path=os.path.join(outputs_path,'green_areas')
if not os.path.exists(outputs_greenareas_path):
    os.mkdir(outputs_greenareas_path)
    
# Set up log file
logger = logging.getLogger('udm-to-citycat-dafni')
logger.setLevel(logging.INFO)
log_file_name = 'udm-to-citycat-dafni-%s.log' %(''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(6)))
fh = logging.FileHandler( Path(join(data_path, outputs_path)) / log_file_name)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)

logger.info('Log file established!')
logger.info('--------')

logger.info('Paths have been setup')  

# get save_logfile status
save_logfile = getenv('save_logfile') # get the type of data to be clipped. raster or vector
if save_logfile is None: # grab the default if the var hasn't been passed
    print('Warning! No save_logfile env passed. Default, False, will be used.')
    save_logfile = False
elif save_logfile.lower() == 'true':
    save_logfile = True
elif save_logfile.lower() == 'false':
    save_logfile = False
else:
    print('Error! Incorrect setting for save logfile parameter (%s)' %save_logfile)
    logger.info('Error! Incorrect setting for save logfile parameter (%s)' % save_logfile)

buildings = glob(inputs_path + "/buildings/*.*", recursive = True)
logger.info(buildings)
e_builds = gpd.read_file(buildings[0])
greens = glob(inputs_path + "/green_areas/*.*", recursive = True)
logger.info(greens)
e_green = gpd.read_file(greens[0])

# If the UDM model preceeds the CityCat model in the workflow, a zip file should appear in the inputs folder
# Check if the zip file exists
archive = glob(inputs_path + "/**/*.zip", recursive = True)
logger.info(archive)

matches = []
for match in archive:
    if "urban_fabric" in match:
        matches.append(match)

if len(matches) ==1 :
    stop_code = 0
    if os.path.exists(matches[0]) :
        with ZipFile(matches[0], 'r') as zip: 
            # extract the files into the inputs directory
            zip.extractall(inputs_path)
        # Create, if needed, the folder structure
        inputs_buildings_path=os.path.join(inputs_path,'buildings')
        if not os.path.exists(inputs_buildings_path):
            os.mkdir(inputs_buildings_path)
        inputs_greenspaces_path=os.path.join(inputs_path,'green_areas')
        if not os.path.exists(inputs_greenspaces_path):
            os.mkdir(inputs_greenspaces_path)
        # Move the relevent files into the correct folders
        #shutil.move(os.path.join(inputs_path,'data','outputs','data','buildings.gpkg'), os.path.join(inputs_buildings_path,'buildings_udm.gpkg'))
        #shutil.move(os.path.join(inputs_path,'data','outputs','data','greenspace.gpkg'), os.path.join(inputs_greenspaces_path,'greenspace_udm.gpkg'))
        shutil.move(os.path.join(inputs_path,'buildings.gpkg'), os.path.join(inputs_buildings_path,'buildings_udm.gpkg'))
        shutil.move(os.path.join(inputs_path,'greenspace.gpkg'), os.path.join(inputs_greenspaces_path,'greenspace_udm.gpkg'))
        zip.close()
        
if len(matches) ==0 :
    # Create a shapefile of the existing buildings to be turned into a text file for citycat
    all_builds = e_builds.to_file(os.path.join(outputs_path,'all_buildings.shp'))
    all_builds = gpd.read_file(os.path.join(outputs_path,'all_buildings.shp'))
    all_builds = all_builds.explode()
    all_builds.reset_index(inplace=True, drop=True)
    all_builds1 = all_builds.to_file(os.path.join(outputs_path,'all_buildings.shp'))
    
    #Create a shapefile of the existing greenspaces to be turned into a text file for citycat
    all_greens = e_green.to_file(os.path.join(outputs_path,'all_greenareas.shp'))
    all_greens = gpd.read_file(os.path.join(outputs_path,'all_greenareas.shp'))
    all_greens = all_greens.explode()
    all_greens.reset_index(inplace=True, drop=True)
    all_greens1 = all_greens.to_file(os.path.join(outputs_path,'all_greenareas.shp'))
    
    # Create a copy of the buildings.gpkg in the outputs path to input into the flood impact model
    src=buildings[0]
    dst=os.path.join(outputs_buildings_path,'all_buildings.gpkg')
    shutil.copy(src,dst)
    
    stop_code = 1

if stop_code == 0 :
    # Read in all of the relevent files from the inputs folder, including the outputs from the udm
    dph_raster = os.path.join(inputs_path,'out_cell_dph_clip.asc')
    buildings = glob(inputs_path + "/buildings/*.*", recursive = True)
    u_builds = gpd.read_file(os.path.join(inputs_path,'buildings','buildings_udm.gpkg'))
    u_builds['building_use'] = 'residential'
    u_builds['toid'] = 'udm' + u_builds.index.astype(str)
    u_green = gpd.read_file(os.path.join(inputs_path,'green_areas','greenspace_udm.gpkg'))
    logger.info('Files read in')

    # Define the projection for each of the geopackages to ensure all projections are the same
    u_builds.set_crs(epsg=27700, inplace=True)
    e_builds.set_crs(epsg=27700, inplace=True)
    e_green.set_crs(epsg=27700, inplace=True)
    u_green.set_crs(epsg=27700, inplace=True)
    print('done')
    
    udm_buildings = u_builds
    existing_builds = e_builds

    # Polygonize the raster to create vectors of the locations of development
    # Taken from the density raster generated by the UDM model
    logger.info('Polygonising the raster')
    with rasterio.open(dph_raster) as src:
        image = src.read(1,out_dtype='uint16')
        mask=image!=0

    results = ({'properties':{'cluster_id':int(v)},'geometry':s}
            for (s,v) in (features.shapes(image, mask=mask, transform=src.transform)))

    geoms=list(results)
    # Turn the results into a geopanda dataframe
    gpd_polygonized_raster =gpd.GeoDataFrame.from_features(geoms)
    gpd_polygonized_raster.set_crs(epsg=27700, inplace=True) 
    # Not needed but useful to output to file to check the results are as expected.
    # gpd_polygonized_raster.to_file(os.path.join(outputs_path,'dph_poly.gpkg'),driver='GPKG')

    # Next we need to check the validity of the dph polygons
    logger.info('Checking the validity of the dph polygons')
    gpd_polygonized_raster.geometry = gpd_polygonized_raster.apply(lambda row: make_valid(row.geometry), axis=1)
    gpd_polygonized_raster['validity'] = gpd_polygonized_raster.apply(lambda row: explain_validity(row.geometry),axis=1)

    # A csv file to check that all polygons are now valid
    # shp[['cluster_id', 'geometry', 'validity']].to_csv(
           # os.path.join(outputs_path, 'validity_check.csv'), index=False,  float_format='%g')

    # Override the geopackage with the fixed polygons
    gpd_polygonized_raster.set_crs(epsg=27700, inplace=True)
    # Not needed but useful to output to file to check the results are as expected / might come in useful for examining city expansion
    gpd_polygonized_raster.to_file(os.path.join(outputs_path,'dph_poly.gpkg'),driver='GPKG')
    shp= gpd.read_file(os.path.join(outputs_path,'dph_poly.gpkg'))

    # Look at the difference between the developed land and exisiting green spaces and output to file
    logger.info('Calculating difference between green spaces and development land')
    res_difference = gpd.overlay(e_green,shp, how='difference')
    #res_difference.to_file(os.path.join(outputs_path,'clipped_greenspace.gpkg'),driver='GPKG')

    # Need to make all sets of building and greenery shapefiles before merging them to avoid losing data
    logger.info('Creating Shapefiles')
    su_builds = u_builds.to_file(os.path.join(outputs_path,'u_buildings.shp'))
    se_builds = e_builds.to_file(os.path.join(outputs_path,'e_buildings.shp'))
    su_green = u_green.to_file(os.path.join(outputs_path,'u_greenarea.shp'))
    se_green = res_difference.to_file(os.path.join(outputs_path,'e_greenarea.shp'))

    # Need to read the shapefiles in so that they can be merged
    # For the city cat set up to run, all multi polygons must be made into polygons and reindexed
    u_builds = gpd.read_file(os.path.join(outputs_path,'u_buildings.shp'))
    u_builds = u_builds.explode()
    u_builds.reset_index(inplace=True, drop=True)
    e_builds = gpd.read_file(os.path.join(outputs_path,'e_buildings.shp'))
    e_builds = e_builds.explode()
    e_builds.reset_index(inplace=True, drop=True)
    u_green = gpd.read_file(os.path.join(outputs_path,'u_greenarea.shp'))
    u_green = u_green.explode()
    u_green.reset_index(inplace=True, drop=True)
    e_green = gpd.read_file(os.path.join(outputs_path,'e_greenarea.shp'))
    e_green = e_green.explode()
    e_green.reset_index(inplace=True, drop=True)

    # Merge the new green areas with the existing green areas 
    # (removing areas that have been developed)
    logger.info('Merging Greenspaces')
    joined_green = u_green.append(e_green)
    all_green = joined_green.to_file(os.path.join(outputs_greenareas_path,'all_greenareas.shp'))

    # Merge the new UDM buildings with the existing buildings
    logger.info('Merging Buildings')
    joined_build = u_builds.append(e_builds)
    all_builds = joined_build.to_file(os.path.join(outputs_buildings_path,'all_buildings.shp'))

    # Delete shape files that are no longer needed
    logger.info('Deleting files that are no longer needed')

    os.remove(os.path.join(outputs_path,'u_buildings.shp'))
    os.remove(os.path.join(outputs_path,'u_buildings.cpg'))
    os.remove(os.path.join(outputs_path,'u_buildings.dbf'))
    os.remove(os.path.join(outputs_path,'u_buildings.prj'))
    os.remove(os.path.join(outputs_path,'u_buildings.shx'))

    os.remove(os.path.join(outputs_path,'e_buildings.shp'))
    os.remove(os.path.join(outputs_path,'e_buildings.cpg'))
    os.remove(os.path.join(outputs_path,'e_buildings.dbf'))
    os.remove(os.path.join(outputs_path,'e_buildings.prj'))
    os.remove(os.path.join(outputs_path,'e_buildings.shx'))

    os.remove(os.path.join(outputs_path,'u_greenarea.shp'))
    os.remove(os.path.join(outputs_path,'u_greenarea.cpg'))
    os.remove(os.path.join(outputs_path,'u_greenarea.dbf'))
    os.remove(os.path.join(outputs_path,'u_greenarea.prj'))
    os.remove(os.path.join(outputs_path,'u_greenarea.shx'))

    os.remove(os.path.join(outputs_path,'e_greenarea.shp'))
    os.remove(os.path.join(outputs_path,'e_greenarea.cpg'))
    os.remove(os.path.join(outputs_path,'e_greenarea.dbf'))
    os.remove(os.path.join(outputs_path,'e_greenarea.prj'))
    os.remove(os.path.join(outputs_path,'e_greenarea.shx'))
    
    os.remove(os.path.join(outputs_path,'dph_poly.gpkg'))
    
    # Merge the udm buildings and existing buildings shapefiles (with the toid and building use added to the udm buildings)
    all_buildings = udm_buildings.append(existing_builds)

    # Need to change the fid column from real to integer (renamed and replaced)
    #all_buildings.rename(columns={"fid":"Check"}, inplace=True)
    #all_buildings['fid'] = np.arange(all_buildings.shape[0])
    
    # Output a gpkg file with all of the buildings to a seperate folder
    #all_buildings.to_file(os.path.join(outputs_buildings_path,'all_buildings.gpkg'),driver='GPKG')

    # final step - delete the log file if requested by user
    if save_logfile is False:
        # delete log file dir
        remove(os.path.join(data_path, outputs_path, log_file_name))
