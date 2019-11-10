import numpy as np
import gdal
import json
import glob
import os
import sys
from osgeo import ogr
from osgeo import osr
import copy
import random

"""
Look here for cheats:
https://pcjericks.github.io/py-gdalogr-cookbook/geometry.html
"""

# GLOBAL CONSTANTS
UNKNOWN_CLASS_ID = 5

class TrainingImage:
    """
    A class for containing data (and metadata) for a training image.
    """

    def __init__(self, data, labels, geo_transform, name="", projection=None):
        if projection is None:
            projection = gdal.osr.SpatialReference()
            projection.ImportFromEPSG(25833)
        self.projection = projection
        self.geo_transform = geo_transform
        if data.shape != labels.shape:
            raise Exception(f"The shape of the data ({data.shape}) and labels ({labels.shape}) did not match")
        self.data = data
        self.labels = labels
        self.shape = data.shape
        self.name = name

    def _write_array_to_raster(self, output_filepath, array):
        """
        Writes the given array to a raster image
        :param output_filepath: The output file
        :return: Nothing
        """

        driver = gdal.GetDriverByName("GTiff")
        raster = driver.Create(output_filepath, self.shape[1], self.shape[0],
                      1, gdal.GDT_Int16)
        raster.SetGeoTransform(self.geo_transform)
        raster.SetProjection(self.projection)
        raster.GetRasterBand(1).WriteArray(array)
        raster = None

    def write_data_to_raster(self, output_filepath):
        self._write_array_to_raster(output_filepath, self.data)

    def write_labels_to_raster(self, output_filepath):
        self._write_array_to_raster(output_filepath, self.labels)


def create_pointer_files(data_path, output_folder, train_size=0.8, valid_size=0.0, test_size=0.2, shuffle=True):
    """
    Make txt files that point to images. Splitts into training, validation and test sets.
    :param output_folder:
    :param random_seed:
    :param data_path:
    :param train_size:
    :param valid_size:
    :param test_size:
    :param shuffle:
    :return:
    """
    total = train_size + test_size + valid_size
    if total != 1:
        raise Exception(f"The sizes don't sum to one, they sum to {total}")
    image_paths = glob.glob(os.path.join(data_path, "images", "*.tif"))
    if shuffle:
        random.shuffle(image_paths)
    label_paths = [path.replace("images", "labels") for path in image_paths]
    os.makedirs(output_folder, exist_ok=True)
    # Make training file
    with open(os.path.join(output_folder, "train.txt"), "w+") as f:
        pairs = [image_paths[i] + ";" + label_paths[i] for i in range(int(train_size*len(image_paths)))]
        f.write("\n".join(pairs))
    # Make validation file
    with open(os.path.join(output_folder, "valid.txt"), "w+") as f:
        end_index = int(train_size * len(image_paths)) + int(valid_size * len(image_paths))
        pairs = [image_paths[i] + ";" + label_paths[i] for i in range(int(train_size * len(image_paths)), end_index)]
        f.write("\n".join(pairs))
    # Make test file
    with open(os.path.join(output_folder, "test.txt"), "w+") as f:
        start_index = int(train_size * len(image_paths)) + int(valid_size * len(image_paths))
        pairs = [image_paths[i] + ";" + label_paths[i] for i in range(start_index, len(image_paths))]
        f.write("\n".join(pairs))


def divide_image(image_filepath, label_filepath, image_size=512):
    # Load image
    image_ds = gdal.Open(image_filepath)
    geo_transform = image_ds.GetGeoTransform()
    projection = image_ds.GetProjection()
    image_matrix = image_ds.GetRasterBand(1).ReadAsArray()
    image_ds = None

    # Load label
    label_ds = gdal.Open(label_filepath)
    if label_ds.GetGeoTransform() != geo_transform:
        raise Exception(f"The geo transforms of image {image_filepath} and label {label_filepath} did not match")
    label_matrix = label_ds.GetRasterBand(1).ReadAsArray()
    label_ds = None

    training_data = []
    # Make properly sized training data
    # Make sure that the whole image is covered, even if the last one has to overlap
    shape_0_indices = list(range(0, image_matrix.shape[0], image_size))
    shape_0_indices[-1] = image_matrix.shape[0] - image_size
    shape_1_indices = list(range(0, image_matrix.shape[1], image_size))
    shape_1_indices[-1] = image_matrix.shape[1] - image_size
    # Split the images
    for shape_0 in shape_0_indices:
        for shape_1 in shape_1_indices:
            labels = label_matrix[shape_0:shape_0 + image_size, shape_1:shape_1 + image_size]
            # Check if the entire image is of the unknown class, if so skip it
            is_unknown_matrix = labels == UNKNOWN_CLASS_ID
            if np.min(is_unknown_matrix) == 1 and np.max(is_unknown_matrix) == 1:
                continue
            data = image_matrix[shape_0:shape_0 + image_size, shape_1:shape_1 + image_size]
            new_geo_transform = list(geo_transform)
            new_geo_transform[0] += shape_1 * geo_transform[1]  # East
            new_geo_transform[3] += shape_0 * geo_transform[5]  # North
            name = os.path.split(image_filepath)[-1].replace(".tif", "") + f"_n_{shape_0}_e_{shape_1}"
            training_data.append(TrainingImage(data, labels, new_geo_transform, name=name, projection=projection))
    return training_data


def divide_and_save_images(image_filepaths, label_filepaths, output_folder=None, image_size=512):
    """
    This function takes big images and splits them into smaller images and saves them to disk
    :param image_filepaths: A list of filepaths to the images that will be loaded
    :param label_filepaths: A list of filepaths to the label (rasters) that will be loaded
    :param output_folder: The folder where the new rasters will be saved. If it is None, the files will not be saved
    :param image_size: The size of the new images, measured in pixels
    :return: list of TrainingImage objects
    """

    # Check that the size of the filepaths are the same are loaded
    if len(image_filepaths) != len(label_filepaths):
        raise Exception(f"The image filepaths and label filepaths must be in sync,"
                        f" but their lengths did not match. {len(image_filepaths)} != {len(label_filepaths)}")
    # Load the images
    training_images = []
    for i in range(len(image_filepaths)):
        training_images += divide_image(image_filepaths[i], label_filepaths[i], image_size=image_size)
    # Write the images to disk
    if output_folder is not None:
        # Make output folders
        os.makedirs(os.path.join(output_folder, "images"), exist_ok=True)
        os.makedirs(os.path.join(output_folder, "labels"), exist_ok=True)
        for image in training_images:
            # Data
            data_path = os.path.join(output_folder, "images", image.name + ".tif")
            image.write_data_to_raster(data_path)
            # Labels
            label_path = os.path.join(output_folder, "labels", image.name + ".tif")
            image.write_labels_to_raster(label_path)
    return training_images


def find_intersecting_polys(geometry, polys):
    intersecting_polys = []
    for poly in polys:
        if poly.Intersects(geometry):
            intersecting_polys.append(poly)
    return intersecting_polys


def rasterize_polygons(polygons, image_path, class_name, shapefile_path, driver=gdal.GetDriverByName("MEM")):
    """
    Retuns a data set image with the bounding box dimensions and the polygon locations marked by 1.
    :param polygons: A list of polygons of the same class
    :param bounding_box: A bounding box. type: Geometry
    :return: Data set image
    """
    # Get meta data from the image
    image_ds = gdal.Open(image_path)
    geo_transform = image_ds.GetGeoTransform()
    projection = image_ds.GetProjection()
    n_pixels_north = image_ds.RasterYSize
    n_pixels_east = image_ds.RasterXSize
    image_ds = None
    # Create empty image
    output_path = image_path.replace(".tif", "")
    output_path += f"_temp_label_{class_name}.tif"
    label_raster = driver.Create(output_path, n_pixels_east, n_pixels_north,
                  1, gdal.GDT_Int16)
    label_raster.SetGeoTransform(geo_transform)
    label_raster.SetProjection(projection)

    # set up the shapefile driver
    shapefile_driver = ogr.GetDriverByName("Memory")
    # create the data source
    poly_ds = shapefile_driver.CreateDataSource(shapefile_path)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(25833)
    layer = poly_ds.CreateLayer(os.path.split(shapefile_path.replace(".shp", ""))[-1],
                                srs, ogr.wkbPolygon)
    # Add the polygons to the new layer
    for poly in polygons:
        feature = ogr.Feature(layer.GetLayerDefn())
        feature.SetGeometry(poly)
        layer.CreateFeature(feature)
        feature.Destroy()

    # Burn the polygons into the new image
    gdal.RasterizeLayer(label_raster, (1,), layer, burn_values=(1,))
    poly_ds.Destroy()
    # Save and close the image


    return label_raster


def find_closest_pixel(i, j, arrays, threshold=10):
    """

    :param i: shape 0 axis index
    :param j: shape 1 axis index
    :param arrays: arrays with labels
    :param threshold: The (max) distance in pixels that are searched
    :return: The class of the closest pixel (majority if there is more than one)
    """
    # Find shape
    shape = None
    for array in arrays:
        if array is not None:
            shape = array.shape
            break
    # Find dimensions of the box
    distance_to_closest_edge = min(i, j, shape[0]-i-1, shape[1]-j-1)
    max_radius = min(threshold, distance_to_closest_edge)
    # Check if there are any classes present
    id_count = [0] * len(arrays)
    total = 0
    for identifier, array in enumerate(arrays):
        if array is not None:
            id_count[identifier] += np.sum(array[i-max_radius:i+max_radius, j-max_radius:j+max_radius])
    if sum(id_count) > 0:
        return np.argmax(id_count)
    else:
        # No class was in the search area, return the ID of the unknown class
        return 5

    # Unreachable code on purpose, it was to slow
    radius = 0
    while radius < max_radius:
        ids = []
        radius += 1
        for search_i in range(i-radius, i+radius+1):
            for search_j in range(j-radius, j+radius+1):
                for identifier, array in enumerate(arrays):
                    if array is None: continue
                    if array[search_i][search_j] > 0:
                        ids.append(identifier)
        id_count = [0]*len(arrays)
        # Find the majority id
        for id in ids:
            id_count[id] += 1
        return np.argmax(id_count)
    # Return the id of the "unknown" class since no other classes where found
    return 5


def merge_labels_rasters(label_raster_dict):
    """

    (array = None is equivalent with a zero array but is kept as None to save computation time)
    :param label_raster_dict:
    :return:
    """
    arrays = []
    s_IDs = sorted(label_raster_dict.keys())
    for id in s_IDs:
        if label_raster_dict[id] is None:
            array = None
        else:
            array = label_raster_dict[id].GetRasterBand(1).ReadAsArray()
        arrays.append(array)
    # Check array shapes, they should all be the same
    shape = None
    for array in arrays:
        if array is not None:
            shape = array.shape
            break
    for array in arrays:
        if array is None: continue
        if array.shape != shape:
            raise Exception(f"The shapes does not match, {shape} != {array.shape}")
    label_matrix = np.zeros(shape, dtype=int)
    for i in range(shape[0]):
        for j in range(shape[1]):
            ids_at_pixel = []
            for id, array in enumerate(arrays):
                if array is None:
                    continue
                else:
                    pixel = array[i][j]
                    if pixel > 0:
                        ids_at_pixel.append(id)
            # Only one class at the location
            if len(ids_at_pixel) == 1:
                label_matrix[i][j] = ids_at_pixel[0]
            # No pixels matches, will fill in with closest value
            elif len(ids_at_pixel) == 0:
                label_matrix[i][j] = find_closest_pixel(i, j, arrays)
            # Multiple pixels at the same loc, take the majority
            elif len(ids_at_pixel) > 1:
                id_count = [0] * len(arrays)
                # Find the majority id
                for id in ids_at_pixel:
                    id_count[id] += 1
                label_matrix[i][j] = np.argmax(id_count)
            else:
                raise Exception("Something weird happened...")
    return label_matrix


def create_raster_labels(image_path, poly_dict, destination_path, driver=gdal.GetDriverByName("GTiff")):
    """
    Creates a raster with all the polygons as pixel values.
    :param image_path: Path to the image that defines the bounding box
    :param poly_dict: A dict with class_ID -> class_polygons
    :return:
    """
    # Skip if the image has a label image already
    if os.path.isfile(destination_path):
        print(f"{destination_path} already exists")
        return None

    # Create bounding box for the image
    image_ds = gdal.Open(image_path)
    bounding_box = create_bounding_box(image_ds)
    label_raster_dict = {}
    for current_class in poly_dict:
        polys = poly_dict[current_class]
        # Find intersecting polygons
        intersecting_polys = find_intersecting_polys(bounding_box, polys)
        if len(intersecting_polys) == 0:
            label_raster_dict[current_class] = None
        else:
            shapefile_path = r"D:\temp\post_processed_label_" + os.path.split(destination_path.replace(".tif", ".shp"))[-1]
            label_raster_dict[current_class] = rasterize_polygons(intersecting_polys, image_path,
                                                                  current_class, shapefile_path)
    # Check if there is any polygons in the image
    have_overlap = False
    for v in label_raster_dict.values():
        if v is not None:
            have_overlap = True
            break
    if not have_overlap:
        # There was no overlapping polygons so there is no point in making a raster for it
        return None
    # Merge the different class layer to one
    label_matrix = merge_labels_rasters(label_raster_dict)
    label_dataset = driver.Create(destination_path, image_ds.RasterXSize, image_ds.RasterYSize,
                                  1, gdal.GDT_Int16)
    label_dataset.SetGeoTransform(image_ds.GetGeoTransform())
    label_dataset.SetProjection(image_ds.GetProjection())
    label_dataset.GetRasterBand(1).WriteArray(label_matrix)
    # Save, the gdal way
    label_dataset = None
    print(f"Wrote label image {image_path} to {destination_path}")


def create_bounding_box(image_ds):
    # Create a bounding box geometry for the image
    geo_transform = image_ds.GetGeoTransform()
    projection = image_ds.GetProjection()
    n_pixels_north = image_ds.RasterYSize
    n_pixels_east = image_ds.RasterXSize
    top_left_coordinate = (geo_transform[0], geo_transform[3])
    bottom_right_coordinate = (geo_transform[0] + n_pixels_east * geo_transform[1],
                               geo_transform[3] + geo_transform[5] * n_pixels_north)
    ring = ogr.Geometry(ogr.wkbLinearRing)
    ring.AddPoint(top_left_coordinate[0], top_left_coordinate[1])  # Top left
    ring.AddPoint(top_left_coordinate[0], bottom_right_coordinate[1])  # Top right
    ring.AddPoint(bottom_right_coordinate[0], bottom_right_coordinate[1])  # Bottom right
    ring.AddPoint(bottom_right_coordinate[0], top_left_coordinate[1])  # Bottom left
    ring.AddPoint(top_left_coordinate[0], top_left_coordinate[1])  # Top left, closes the ring
    rectangle = ogr.Geometry(ogr.wkbPolygon)
    rectangle.AddGeometry(ring)
    ref = osr.SpatialReference()
    ref.ImportFromEPSG(25833)
    rectangle.AssignSpatialReference(ref)
    return rectangle


def name_to_id(name):
    name = name.lower()
    if name == "water":
        return 0
    elif name == "gravel":
        return 1
    elif name == "vegetation":
        return 2
    elif name == "farmland":
        return 3
    elif name == "human-constructions" or name == "human-construction":
        return 4
    elif name == "undefined":
        return 5
    else:
        print(f"WARNING: could not assign the name {name} to an id")
        return None


def load_polygons(folder_path):
    """
    Loads all the shapefiles in the folder into gdal geometries.
    :param folder_path: The path to the shapefile folder
    :return: A dict with ID -> label geometry
    """
    id_poly_dict = {}
    filepaths = glob.glob(os.path.join(folder_path, "*.shp"))
    print(f"Filepaths: {filepaths}")
    for path in filepaths:
        # Get the ID corresponding to the name
        last_part_of_path = os.path.split(path)[-1].replace(".shp", "")
        identifier = name_to_id(last_part_of_path.split("_")[-1])

        # Load the shapefile into a geometry
        driver = ogr.GetDriverByName("ESRI Shapefile")
        ds = driver.Open(path, 0)
        layer = ds.GetLayer()
        polys = []
        for feature in layer:
            geom = feature.GetGeometryRef().Clone()
            ref = osr.SpatialReference()
            ref.ImportFromEPSG(25833)
            geom.AssignSpatialReference(ref)
            polys.append(geom)
        id_poly_dict[identifier] = polys
    return id_poly_dict


def process_and_rasterize_raw_data():
    gdal.UseExceptions()
    # Define the paths to the aerial images
    ORTO_ROOT_FOLDER_PATH = r"D:\ortofoto"
    # Define the path to the labels
    LABEL_ROOT_PATH = r"D:\labels\refined_OD_labels"
    # Define the river folders that will be processed
    RIVER_SUBFOLDER_NAMES = ["gaula_1963", "lærdal_1976"]
    # Destination root path
    DEST_ROOT_PATH = r"D:\labels\rasters"

    # Create label rasters
    for subfolder in RIVER_SUBFOLDER_NAMES:
        # Images
        orto_folder_path = os.path.join(ORTO_ROOT_FOLDER_PATH, subfolder)
        image_paths = glob.glob(os.path.join(orto_folder_path, "*.tif"))
        # Labels
        label_folder_path = os.path.join(LABEL_ROOT_PATH, subfolder)
        # Get polygons
        id_poly_dict = load_polygons(label_folder_path)
        # Create raster labels for the area covered by the image
        for path in image_paths:
            create_raster_labels(path, id_poly_dict,
                                 os.path.join(DEST_ROOT_PATH, subfolder, "label" + os.path.split(path)[-1]))
    print("Done!")

def main():
    gdal.UseExceptions()
    # Define the paths to the aerial images
    ORTO_ROOT_FOLDER_PATH = r"D:\ortofoto"
    # Define path to label rasters
    LABEL_RASTER_ROOT_FOLDER = r"D:\labels\rasters"
    # Define the river folders that will be processed
    RIVER_SUBFOLDER_NAMES = ["gaula_1963", "lærdal_1976"]
    # Destination root path
    DEST_ROOT_PATH = r"D:\tiny_images\01"
    DEST_ROOT_PATH = None

    # Create label rasters
    label_paths = []
    image_paths = []
    for subfolder in RIVER_SUBFOLDER_NAMES:
        # Images
        label_folder_path = os.path.join(LABEL_RASTER_ROOT_FOLDER, subfolder)
        l_paths = glob.glob(os.path.join(label_folder_path, "*.tif"))
        label_paths += l_paths
        for l_path in l_paths:
            name = os.path.split(l_path)[-1].replace("label", "")
            image_path = os.path.join(ORTO_ROOT_FOLDER_PATH, subfolder, name)
            image_paths.append(image_path)
    divide_and_save_images(image_paths, label_paths, DEST_ROOT_PATH)


if __name__ == '__main__':
    random.seed(54635)
    create_pointer_files(r"D:\tiny_images\01", r"D:\pointers\01")
