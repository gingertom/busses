import numpy as np
import numpy.ma as ma
import pandas as pd
import datetime
import feather

# from sklearn.linear_model import LinearRegression

# from sklearn.metrics import mean_squared_error, mean_absolute_error

import os

# import xgboost as xgb

# import plaidml.keras

# plaidml.keras.install_backend()

import keras
from keras.preprocessing import sequence
from keras import layers, Input, Model
from keras.models import Sequential
from keras.layers import Flatten, Dense, Lambda, LSTM, Dropout

from sklearn import preprocessing

# from sklearn.ensemble import RandomForestRegressor

from argparse import ArgumentParser
import os.path
from pathlib import Path


# os.environ["KMP_DUPLICATE_LIB_OK"] = "True"


def filter_rare(stop_events):

    segment_counts = stop_events.groupby("segment_code").size()

    filtered_stop_events = stop_events.drop(
        stop_events[
            stop_events["segment_code"].isin(
                segment_counts[segment_counts < 120].index.values
            )
        ].index
    )

    return filtered_stop_events


def drop_features(se):

    se = se.drop(
        labels=[
            "test",
            "train",
            "direction",
            "midpoint_lon",
            "midpoint_lat",
            "publicName",
            "stopCode",
            "vehicle",
            "workid",
            "patternId",
            "prev_timingPoint",
            "prev_stopCode",
            "segment_code",
            "segment_name",
            "prev_segment_code_5",
            "prev_segment_code_4",
            "prev_segment_code_3",
            "prev_segment_code_2",
            "prev_segment_code_1",
            "next_segment_code_5",
            "next_segment_code_4",
            "next_segment_code_3",
            "next_segment_code_2",
            "next_segment_code_1",
            "prev_event_index_5",
            "prev_event_index_4",
            "prev_event_index_3",
            "prev_event_index_2",
            "prev_event_index_1",
            "next_event_index_5",
            "next_event_index_4",
            "next_event_index_3",
            "next_event_index_2",
            "next_event_index_1",
            "id",
        ],
        axis=1,
    )

    se = se.drop(
        labels=[
            "aimedArrival",
            "aimedDeparture",
            "actualArrival",
            "actualDeparture",
            "prev_aimedArrival",
            "prev_aimedDeparture",
            "prev_actualArrival",
            "prev_actualDeparture",
            "arrival_5mins",
            "offset_timestamp_5_1",
            "offset_timestamp_5_2",
            "offset_timestamp_5_3",
            "offset_timestamp_5_4",
        ],
        axis=1,
    )

    se = se.drop(
        labels=[
            "diff_percent_segment_and_median_by_segment_code",
            "dwell_duration_dest",
            "dwell_duration_prev",
            "full_duration",
            "diff_full_segment_and_median_by_segment_code",
            "diff_full_segment_and_median_by_segment_code_and_hour_and_day",
            "diff_percent_full_segment_and_median_by_segment_code",
            "diff_percent_full_segment_and_median_by_segment_code_and_hour_and_day",
            "diff_segment_and_median_by_segment_code",
            "diff_segment_and_median_by_segment_code_and_hour_and_day",
            "diff_percent_segment_and_median_by_segment_code",
        ],
        axis=1,
    )

    return se


def tidy_up(se):

    se = pd.get_dummies(se, columns=["arrival_hour", "arrival_day"])

    se = se.dropna(
        subset=["diff_percent_segment_and_median_by_segment_code_and_hour_and_day"]
    )

    se["clock_direction_degrees"] = se["clock_direction_degrees"].replace(
        np.nan, np.mean(se["clock_direction_degrees"])
    )

    se = prep_spatiotemporal(se)

    se = se.replace(np.nan, 0)

    to_remove = ["mean", "prev_stop_", "next_stop_", "road"]

    min_cols = [c for c in se.columns if not any(x in c for x in to_remove)]

    se_min = se[min_cols]

    to_remove_timeless = ["mean", "prev_stop_", "next_stop_", "road", "self_offset_"]

    min_cols_timeless = [
        c for c in se.columns if not any(x in c for x in to_remove_timeless)
    ]

    se_timeless = se[min_cols_timeless]

    return se, se_min, se_timeless


def split_train_test(events, days):

    first_day = events["date"].min()

    #     days = 75

    train = events.loc[events["date"].isin(pd.date_range(first_day, periods=days))]

    test = events.loc[
        events["date"].isin(
            pd.date_range(first_day + pd.Timedelta(f"{days + 1} day"), periods=14)
        )
    ]

    return train, test


def prep_matrices(se, se_min, se_timeless, days):

    train, test = split_train_test(se_min, days)

    train_timeless, test_timeless = split_train_test(se_timeless, days)

    train_st, test_st = split_train_test(
        se[
            [
                "road_time_series",
                "date",
                "diff_percent_segment_and_median_by_segment_code_and_hour_and_day",
                "segment_duration",
            ]
        ],
        days,
    )

    # train_matrix = stop_events[stop_events['train']][['line_distance', 'to_centre_dist', 'direction_degrees', 'best_0', 'best_1', 'best_2', 'best_3', 'best_4', 'best_5', 'best_6', 'best_7', 'best_8', 'best_9', '30', '31', '32', '33', '34', '35', '36', '37', '38', '39']].values
    train_matrix = train.drop(
        [
            "diff_percent_segment_and_median_by_segment_code_and_hour_and_day",
            "date",
            "segment_duration",
        ],
        axis=1,
    )
    train_matrix_timeless = train_timeless.drop(
        [
            "diff_percent_segment_and_median_by_segment_code_and_hour_and_day",
            "date",
            "segment_duration",
        ],
        axis=1,
    )
    train_matrix_st = train_st.drop(
        [
            "diff_percent_segment_and_median_by_segment_code_and_hour_and_day",
            "date",
            "segment_duration",
        ],
        axis=1,
    )
    train_target = train[
        "diff_percent_segment_and_median_by_segment_code_and_hour_and_day"
    ]

    # test_matrix = stop_events[stop_events['test']][['line_distance', 'to_centre_dist', 'direction_degrees', 'best_0', 'best_1', 'best_2', 'best_3', 'best_4', 'best_5', 'best_6', 'best_7', 'best_8', 'best_9', '30', '31', '32', '33', '34', '35', '36', '37', '38', '39']].values
    test_matrix = test.drop(
        [
            "diff_percent_segment_and_median_by_segment_code_and_hour_and_day",
            "date",
            "segment_duration",
        ],
        axis=1,
    )
    test_matrix_timeless = test_timeless.drop(
        [
            "diff_percent_segment_and_median_by_segment_code_and_hour_and_day",
            "date",
            "segment_duration",
        ],
        axis=1,
    )
    test_matrix_st = test_st.drop(
        [
            "diff_percent_segment_and_median_by_segment_code_and_hour_and_day",
            "date",
            "segment_duration",
        ],
        axis=1,
    )
    test_target = test[
        "diff_percent_segment_and_median_by_segment_code_and_hour_and_day"
    ]

    train_target = np.nan_to_num(train_target)
    test_target = np.nan_to_num(test_target)

    train_target = np.clip(train_target, -1000, 10000)
    test_target = np.clip(test_target, -1000, 10000)

    train_matrix_st = np.array(train_matrix_st.values.tolist()).squeeze()
    test_matrix_st = np.array(test_matrix_st.values.tolist()).squeeze()

    scaler_matrix = preprocessing.StandardScaler().fit(train_matrix)

    train_matrix_scaled = scaler_matrix.transform(train_matrix)
    test_matrix_scaled = scaler_matrix.transform(test_matrix)

    scaler_timeless = preprocessing.StandardScaler().fit(train_matrix_timeless)

    train_matrix_timeless = scaler_timeless.transform(train_matrix_timeless)
    test_matrix_timeless = scaler_timeless.transform(test_matrix_timeless)

    scaler_target = preprocessing.StandardScaler().fit(train_target[:, None])

    train_target_scaled = scaler_target.transform(train_target[:, None])
    test_target_scaled = scaler_target.transform(test_target[:, None])

    st_scaler = preprocessing.StandardScaler()
    train_matrix_st_shape = train_matrix_st.shape
    test_matrix_st_shape = test_matrix_st.shape
    train_matrix_st = st_scaler.fit_transform(
        train_matrix_st.reshape(len(train_target_scaled), -1)
    ).reshape(train_matrix_st_shape)

    test_matrix_st = st_scaler.transform(
        test_matrix_st.reshape(len(test_target_scaled), -1)
    ).reshape(test_matrix_st_shape)

    return (
        train_matrix,
        train_target,
        test_matrix,
        test_target,
        train_matrix_scaled,
        train_target_scaled,
        test_matrix_scaled,
        test_target_scaled,
        train_matrix_st,
        test_matrix_st,
        train_matrix_timeless,
        test_matrix_timeless,
        scaler_target,
        test["median_durations_by_segment_code_and_hour_and_day"].values,
        test["self_offset_5_1"].values,
        test["segment_duration"].values,
    )


def prep_spatiotemporal(se):

    se["self_offset_5_1"] = se["self_offset_5_1"].fillna(0)

    for i in range(2, 5):
        se[f"self_offset_5_{i}"] = se[f"self_offset_5_{i}"].fillna(
            se[f"self_offset_5_{i-1}"]
        )

    for i in range(1, 5):
        for j in range(1, 5):

            if i == 1:
                se[f"prev_stop_1_offset_5_{j}"] = se[
                    f"prev_stop_1_offset_5_{j}"
                ].fillna(se[f"self_offset_5_{j}"])

                se[f"next_stop_1_offset_5_{j}"] = se[
                    f"next_stop_1_offset_5_{j}"
                ].fillna(se[f"self_offset_5_{j}"])
            else:
                se[f"prev_stop_{i}_offset_5_{j}"] = se[
                    f"prev_stop_{i}_offset_5_{j}"
                ].fillna(se[f"prev_stop_{i-1}_offset_5_{j}"])

                se[f"next_stop_{i}_offset_5_{j}"] = se[
                    f"prev_stop_{i}_offset_5_{j}"
                ].fillna(se[f"prev_stop_{i-1}_offset_5_{j}"])

    se["road_offset_5_1"] = se[
        [
            "prev_stop_4_offset_5_1",
            "prev_stop_3_offset_5_1",
            "prev_stop_2_offset_5_1",
            "prev_stop_1_offset_5_1",
            "self_offset_5_1",
            "next_stop_1_offset_5_1",
            "next_stop_2_offset_5_1",
            "next_stop_3_offset_5_1",
            "next_stop_4_offset_5_1",
        ]
    ].values.tolist()

    se["road_offset_5_2"] = se[
        [
            "prev_stop_4_offset_5_2",
            "prev_stop_3_offset_5_2",
            "prev_stop_2_offset_5_2",
            "prev_stop_1_offset_5_2",
            "self_offset_5_2",
            "next_stop_1_offset_5_2",
            "next_stop_2_offset_5_2",
            "next_stop_3_offset_5_2",
            "next_stop_4_offset_5_2",
        ]
    ].values.tolist()

    se["road_offset_5_3"] = se[
        [
            "prev_stop_4_offset_5_3",
            "prev_stop_3_offset_5_3",
            "prev_stop_2_offset_5_3",
            "prev_stop_1_offset_5_3",
            "self_offset_5_3",
            "next_stop_1_offset_5_3",
            "next_stop_2_offset_5_3",
            "next_stop_3_offset_5_3",
            "next_stop_4_offset_5_3",
        ]
    ].values.tolist()

    se["road_offset_5_4"] = se[
        [
            "prev_stop_4_offset_5_4",
            "prev_stop_3_offset_5_4",
            "prev_stop_2_offset_5_4",
            "prev_stop_1_offset_5_4",
            "self_offset_5_4",
            "next_stop_1_offset_5_4",
            "next_stop_2_offset_5_4",
            "next_stop_3_offset_5_4",
            "next_stop_4_offset_5_4",
        ]
    ].values.tolist()

    se["road_time_series"] = se[
        ["road_offset_5_1", "road_offset_5_2", "road_offset_5_3", "road_offset_5_4"]
    ].values.tolist()

    return se


def sort_data(se, days):

    se = filter_rare(se)

    se = drop_features(se)

    se, se_min, se_timeless = tidy_up(se)

    return prep_matrices(se, se_min, se_timeless, days)


def create_fully_connected_large(input_width, dropout):
    model = Sequential()

    model.add(Dense(128, input_shape=(input_width,), activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(62, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(32, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(12, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(12, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(1, activation="tanh"))
    model.summary()

    return model


def create_LSTM_large(input_shape, dropout, recurant_dropout):

    model = Sequential()

    # New Start
    model.add(LSTM(80, input_shape=input_shape, recurrent_dropout=recurant_dropout))

    # Old start
    # model.add(LSTM(40, input_shape=input_shape))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(128, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(64, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(32, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(12, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(12, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(1, activation="tanh"))
    model.summary()

    return model


def create_LSTM_deep(input_shape, dropout, recurant_dropout):

    model = Sequential()

    # New Start
    model.add(
        LSTM(
            40,
            input_shape=input_shape,
            return_sequences=True,
            recurrent_dropout=recurant_dropout,
        )
    )
    model.add(LSTM(40, recurrent_dropout=recurant_dropout))

    # Old start
    # model.add(LSTM(40, input_shape=input_shape))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(128, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(64, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(32, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(12, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(12, activation="relu"))
    model.add(layers.Dropout(rate=dropout))
    model.add(Dense(1, activation="tanh"))
    model.summary()

    return model


def create_combined_model_large(
    road_input_shape, aux_input_shape, dropout, recurant_dropout
):

    # with help from: https://keras.io/getting-started/functional-api-guide/

    # Headline input: meant to receive road time series.
    main_input = Input(shape=road_input_shape, dtype="float32", name="road_time_input")
    lstm_out = LSTM(80, recurrent_dropout=recurant_dropout)(main_input)

    auxiliary_output = Dense(1, activation="tanh", name="aux_output")(lstm_out)

    auxiliary_input = Input(shape=(aux_input_shape,), name="aux_input")
    x = keras.layers.concatenate([lstm_out, auxiliary_input])

    # We stack a deep densely-connected network on top
    x = Dense(128, activation="relu")(x)
    x = Dropout(rate=dropout)(x)
    x = Dense(64, activation="relu")(x)
    x = Dropout(rate=dropout)(x)
    x = Dense(32, activation="relu")(x)
    x = Dropout(rate=dropout)(x)
    x = Dense(12, activation="relu")(x)
    x = Dropout(rate=dropout)(x)
    x = Dense(12, activation="relu")(x)
    x = Dropout(rate=dropout)(x)

    # And finally we add the main output layer
    main_output = Dense(1, activation="tanh", name="main_output")(x)

    model = Model(
        inputs=[main_input, auxiliary_input], outputs=[main_output, auxiliary_output]
    )

    model.summary()

    return model


def create_combined_model_deep(
    road_input_shape, aux_input_shape, dropout, recurant_dropout
):

    # with help from: https://keras.io/getting-started/functional-api-guide/

    # Headline input: meant to receive road time series.
    main_input = Input(shape=road_input_shape, dtype="float32", name="road_time_input")
    lstm_out = LSTM(40, recurrent_dropout=recurant_dropout, return_sequences=True)(
        main_input
    )
    lstm_out = LSTM(40, recurrent_dropout=recurant_dropout)(lstm_out)

    auxiliary_output = Dense(1, activation="tanh", name="aux_output")(lstm_out)

    auxiliary_input = Input(shape=(aux_input_shape,), name="aux_input")
    x = keras.layers.concatenate([lstm_out, auxiliary_input])

    # We stack a deep densely-connected network on top
    x = Dense(128, activation="relu")(x)
    x = Dropout(rate=dropout)(x)
    x = Dense(64, activation="relu")(x)
    x = Dropout(rate=dropout)(x)
    x = Dense(32, activation="relu")(x)
    x = Dropout(rate=dropout)(x)
    x = Dense(12, activation="relu")(x)
    x = Dropout(rate=dropout)(x)
    x = Dense(12, activation="relu")(x)
    x = Dropout(rate=dropout)(x)

    # And finally we add the main output layer
    main_output = Dense(1, activation="tanh", name="main_output")(x)

    model = Model(
        inputs=[main_input, auxiliary_input], outputs=[main_output, auxiliary_output]
    )

    model.summary()

    return model


def full_connected(
    train_matrix_scaled,
    train_target_scaled,
    test_matrix_scaled,
    days,
    scaler_target,
    dropout,
):

    model = create_fully_connected_large(train_matrix.shape[1], dropout)

    Path(f"Data Exploration/models {days}days").mkdir(parents=True, exist_ok=True)

    callbacks_list = [
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=2),
        keras.callbacks.ModelCheckpoint(
            filepath=f"Data Exploration/models {days}days/full_conn_model.h5",
            monitor="val_loss",
            save_best_only=True,
        ),
    ]

    model.compile(optimizer="rmsprop", loss="mean_absolute_error")
    model.fit(
        train_matrix_scaled,
        train_target_scaled,
        epochs=100,
        callbacks=callbacks_list,
        batch_size=512,
        validation_data=(test_matrix_scaled, test_target_scaled),
    )

    test_y_scaled = model.predict(test_matrix_scaled)

    return scaler_target.inverse_transform(test_y_scaled).squeeze()


def lstm(
    train_matrix_st,
    train_target_scaled,
    test_matrix_st,
    days,
    scaler_target,
    dropout,
    recurant_dropout,
    size,
):

    if size == "deep":
        model = create_LSTM_deep(
            (train_matrix_st.shape[1], train_matrix_st.shape[2]),
            dropout,
            recurant_dropout,
        )

    if size == "large":
        model = create_LSTM_large(
            (train_matrix_st.shape[1], train_matrix_st.shape[2]),
            dropout,
            recurant_dropout,
        )

    Path(f"Data Exploration/models {days}days").mkdir(parents=True, exist_ok=True)

    callbacks_list = [
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=2),
        keras.callbacks.ModelCheckpoint(
            filepath=f"Data Exploration/models {days}days/lstm_model.h5",
            monitor="val_loss",
            save_best_only=True,
        ),
    ]

    model.compile(optimizer="rmsprop", loss="mean_absolute_error")
    model.fit(
        train_matrix_st,
        train_target_scaled,
        epochs=100,
        callbacks=callbacks_list,
        batch_size=512,
        validation_data=(test_matrix_st, test_target_scaled),
    )

    test_y_scaled = model.predict(test_matrix_st)

    return scaler_target.inverse_transform(test_y_scaled).squeeze()


def combined(
    train_matrix_scaled,
    test_matrix_scaled,
    train_matrix_st,
    train_target_scaled,
    test_matrix_st,
    days,
    scaler_target,
    dropout,
    recurant_dropout,
    intermediate_weight,
    size,
):

    if size == "large":
        model = create_combined_model_large(
            (train_matrix_st.shape[1], train_matrix_st.shape[2]),
            train_matrix_scaled.shape[1],
            dropout,
            recurant_dropout,
        )

    if size == "deep":
        model = create_combined_model_deep(
            (train_matrix_st.shape[1], train_matrix_st.shape[2]),
            train_matrix_scaled.shape[1],
            dropout,
            recurant_dropout,
        )

    Path(f"Data Exploration/models {days}days").mkdir(parents=True, exist_ok=True)

    callbacks_list = [
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=2),
        keras.callbacks.ModelCheckpoint(
            filepath=f"Data Exploration/models {days}days/combined_model.h5",
            monitor="val_loss",
            save_best_only=True,
        ),
    ]

    model.compile(
        optimizer="rmsprop",
        loss="mean_absolute_error",
        # metrics=["MAE"],
        loss_weights=[1, intermediate_weight],
    )
    model.fit(
        [train_matrix_st, train_matrix_scaled],
        [train_target_scaled, train_target_scaled],
        epochs=100,
        callbacks=callbacks_list,
        batch_size=512,
        validation_data=(
            [test_matrix_st, test_matrix_scaled],
            [test_target_scaled, test_target_scaled],
        ),
    )

    test_y_scaled, _ = model.predict([test_matrix_st, test_matrix_scaled])

    return scaler_target.inverse_transform(test_y_scaled).squeeze()


def MAPE(forecast, actual):

    if len(forecast) != len(actual):
        raise ValueError(
            "Could not calculate MAPE, forecast and actual arrays are different length"
        )

    forecast = np.asarray(forecast)
    actual = np.asarray(actual)

    with np.errstate(divide="ignore", invalid="ignore"):

        division = (actual - forecast) / actual

        division[actual == 0] = 0

        # Instead of dividing by n we count by the number of non-zero values.
        # Essentially ignoring all cases where the actual value is zero.
        mape = 100 / np.count_nonzero(actual) * np.sum(np.abs(division))

    return mape


def make_prediction(test, results):
    return test * (1 + (results / 100))


def is_valid_file(parser, arg):
    if not os.path.exists(arg):
        parser.error("The file %s does not exist!" % arg)
    else:
        return arg  # return a filename


if __name__ == "__main__":

    parser = ArgumentParser(description="Do kitchen sink predictions")
    parser.add_argument(
        "-i",
        dest="input_filename",
        required=True,
        help="input feather file from a previous step",
        metavar="FILE",
        type=lambda x: is_valid_file(parser, x),
    )

    parser.add_argument(
        "-d", dest="days", required=True, help="number of days", type=int
    )

    args = parser.parse_args()

    from_path = Path(args.input_filename)

    print("Loading data...")
    # Load in the stop_events from the previous stage in the pipeline
    stop_events = feather.read_dataframe(args.input_filename)
    stop_events = stop_events.set_index("index")

    # Ensure that the segment code is using the previous
    # timing point not the current one as we use  the previous
    # dwell time.
    # stop_events["segment_code"] = (
    #     stop_events.prev_stopCode
    #     + "_"
    #     + stop_events.stopCode
    #     + "_"
    #     + stop_events.prev_timingPoint.str[0]
    # )

    print("\tLoaded")

    print("Sorting Data...")
    days = args.days

    (
        train_matrix,
        train_target,
        test_matrix,
        test_target,
        train_matrix_scaled,
        train_target_scaled,
        test_matrix_scaled,
        test_target_scaled,
        train_matrix_st,
        test_matrix_st,
        train_matrix_timeless,
        test_matrix_timeless,
        scaler_target,
        test_medians,
        test_self_offset,
        test_durations,
    ) = sort_data(stop_events, args.days)

    print("\tSorted")

    # predict_reg = make_prediction(
    #     test_medians, linear_reg(train_matrix, train_target, test_matrix)
    # )

    # predict_xg = make_prediction(
    #     test_medians, XGBoost_reg(train_matrix, train_target, test_matrix, days)
    # )

    # predict_rf = make_prediction(
    #     test_medians, RF_reg(train_matrix, train_target, test_matrix, days)
    # )

    with open(f"timeless-results-{days}.csv", "w") as file:

        file.write("method,dropout,recurant_dropout,loss_weight,size,MAPE\n")
        file.write(f"medians,nan,nan,nan,nan,{MAPE(test_medians, test_durations)}\n")
        file.write(
            f"self_offset,nan,nan,nan,nan,{MAPE(test_self_offset, test_durations)}\n"
        )
        file.flush()

        dropout = 0
        recurant_dropout = 0.125
        intermediate_weight = 0.2

        for i in range(5):

            for size in ["large", "deep"]:

                predict_NN = make_prediction(
                    test_medians,
                    full_connected(
                        train_matrix_scaled,
                        train_target_scaled,
                        test_matrix_scaled,
                        days,
                        scaler_target,
                        dropout,
                    ),
                )

                file.write(
                    f"NN_time,{dropout},nan,nan,{size},{MAPE(predict_NN, test_durations)}\n"
                )
                file.flush()

                predict_NN = make_prediction(
                    test_medians,
                    full_connected(
                        train_matrix_timeless,
                        train_target_scaled,
                        test_matrix_timeless,
                        days,
                        scaler_target,
                        dropout,
                    ),
                )

                file.write(
                    f"NN_timeless,{dropout},nan,nan,{size},{MAPE(predict_NN, test_durations)}\n"
                )
                file.flush()

                predict_NN_lstm = make_prediction(
                    test_medians,
                    lstm(
                        train_matrix_st,
                        train_target_scaled,
                        test_matrix_st,
                        days,
                        scaler_target,
                        dropout,
                        recurant_dropout,
                        size,
                    ),
                )

                file.write(
                    f"LSTM,{dropout},{recurant_dropout},nan,{size},{MAPE(predict_NN_lstm, test_durations)}\n"
                )
                file.flush()

                predict_NN_combined = make_prediction(
                    test_medians,
                    combined(
                        train_matrix_scaled,
                        test_matrix_scaled,
                        train_matrix_st,
                        train_target_scaled,
                        test_matrix_st,
                        days,
                        scaler_target,
                        dropout,
                        recurant_dropout,
                        intermediate_weight,
                        size,
                    ),
                )

                file.write(
                    f"Combo_time,{dropout},{recurant_dropout},nan,{size},{MAPE(predict_NN_combined, test_durations)}\n"
                )
                file.flush()

                predict_NN_combined = make_prediction(
                    test_medians,
                    combined(
                        train_matrix_timeless,
                        test_matrix_timeless,
                        train_matrix_st,
                        train_target_scaled,
                        test_matrix_st,
                        days,
                        scaler_target,
                        dropout,
                        recurant_dropout,
                        intermediate_weight,
                        size,
                    ),
                )

                file.write(
                    f"Combo_timeless,{dropout},{recurant_dropout},nan,{size},{MAPE(predict_NN_combined, test_durations)}\n"
                )
                file.flush()
