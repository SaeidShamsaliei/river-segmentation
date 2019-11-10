from tensorflow import keras
import tensorflow as tf
import numpy as np
import os
import sys
import gdal



def conv_block(x, kernel_size=5, number_of_convolutions=3, filters=32, activation="relu"):
    for i in range(number_of_convolutions):
        x = keras.layers.Conv2D(filters, kernel_size,
                                activation=activation,
                                padding="same")(x)
    return x

def deconv_block(x, kernel_size=5, number_of_convolutions=3, filters=32, activation="relu"):
    for i in range(number_of_convolutions-1):
        x = keras.layers.Conv2DTranspose(filters, kernel_size,
                                         activation=activation, padding="same")(x)

    x = keras.layers.Conv2DTranspose(filters, kernel_size,
                                     activation=activation, padding="same",
                                     strides=(2, 2))(x)
    return x


def unet(input_shape, depth=3, kernel_size=5, number_of_convolutions=3, filters=32, activation="relu", n_classes=6):
    inputs = keras.layers.Input(shape=input_shape)
    x = inputs
    skip_connections = []
    # Downsample
    for i, d in enumerate(range(depth)):
        x = conv_block(x, kernel_size=kernel_size,
                      number_of_convolutions=number_of_convolutions,
                      filters=filters,
                      activation=activation)

        skip_connections.append(x)
        x = keras.layers.MaxPooling2D()(x)

    # Upsample
    for d in reversed(range(depth)):
        x = deconv_block(x, kernel_size=kernel_size,
                      number_of_convolutions=number_of_convolutions,
                      filters=filters,
                      activation=activation)
        x = tf.concat([x, skip_connections[d]], -1)
    x = conv_block(x, kernel_size=kernel_size,
                      number_of_convolutions=number_of_convolutions,
                      filters=filters,
                      activation=activation)
    x = keras.layers.Conv2D(n_classes, (1, 1), activation="softmax", padding="same")(x)
    return inputs, x


def main(depth=3, kernel_size=5, number_of_convolutions=3, filters=32, activation="relu", n_classes=6):
    images = []  # TODO
    # Make dataset
    train_set_X = None
    train_set_y = None
    for i, image in enumerate(images):
        if i == 0:
            train_set_X = image.data
            train_set_X = np.expand_dims(train_set_X, 0)
            train_set_y = image.labels
            train_set_y = np.expand_dims(train_set_y, 0)
        else:
            train_set_X = np.concatenate([train_set_X, np.expand_dims(image.data, 0)], 0)
            train_set_y = np.concatenate([train_set_y, np.expand_dims(image.labels, 0)], 0)
    # Add channel axis
    train_set_X = np.expand_dims(train_set_X, -1)
    train_set_y = np.expand_dims(train_set_y, -1)

    inputs, outputs = unet(train_set_X.shape[1:])
    model = keras.models.Model(inputs=inputs, outputs=outputs)
    # model.compile("SGD", loss="sparse_categorical_crossentropy", metrics=[keras.metrics.MeanIoU(num_classes=6)])
    model.compile("SGD", loss="sparse_categorical_crossentropy", metrics=["accuracy"])
    model.fit(train_set_X, train_set_y, epochs=10, batch_size=8)


if __name__ == '__main__':
    main()
