import os
import matplotlib.pyplot as plt
from skimage import io
from skimage.measure import block_reduce
from copy import deepcopy
import numpy as np

from sensor import sensor_work
from parameter import *
from utils import *


class Env:
    def __init__(self, episode_index, plot=False):
        self.episode_index = episode_index
        self.plot = plot
        self.ground_truth, initial_cell = self.import_ground_truth(episode_index)
        self.ground_truth_size = np.shape(self.ground_truth)  # cell
        self.cell_size = CELL_SIZE  # meter

        self.robot_belief = np.ones(self.ground_truth_size) * 127
        self.belief_origin_x = -np.round(initial_cell[0] * self.cell_size, 1)   # meter. Convert the image origin (top left) to the current origin at where the robot is initially placed
        self.belief_origin_y = -np.round(initial_cell[1] * self.cell_size, 1)  # meter

        self.sensor_range = SENSOR_RANGE  # meter
        self.explored_rate = 0

        self.done = False

        self.robot_belief = sensor_work(initial_cell, self.sensor_range / self.cell_size, self.robot_belief,
                                        self.ground_truth)
        self.belief_info = Map_info(self.robot_belief, self.belief_origin_x, self.belief_origin_y, self.cell_size)
        self.ground_truth_info = Map_info(self.ground_truth, self.belief_origin_x, self.belief_origin_y, self.cell_size)
        ground_truth_free, _ = get_local_node_coords(np.array([0.0, 0.0]), self.ground_truth_info)
        free, _ = get_local_node_coords(np.array([0.0, 0.0]), self.belief_info)  #Free space nodes in meters. This 
        choice = np.random.choice(free.shape[0], N_AGENTS, replace=False)
        starts = free[choice]
        
        mean_starts = np.mean(starts, axis = 0)
        max_dist = np.max(np.linalg.norm(ground_truth_free - mean_starts, axis = 1))
        possible_target_idx = np.array(np.argwhere(np.linalg.norm(ground_truth_free - mean_starts, axis = 1)>(max_dist -5))).squeeze()
        target_idx = np.random.choice(possible_target_idx)
        self.target = ground_truth_free[target_idx]
        self.robot_locations = np.array(starts)

        robot_cells = get_cell_position_from_coords(self.robot_locations, self.belief_info)  #robot_cells is robot position in pixel coordinate
        for robot_cell in robot_cells:
            self.robot_belief = sensor_work(robot_cell, self.sensor_range / self.cell_size, self.robot_belief,
                                            self.ground_truth)  #This gets the robot belief in pixel coordinates
        self.old_belief = deepcopy(self.robot_belief)
        self.global_frontiers = get_frontier_in_map(self.belief_info)  #frontier in meters coordinate.

        if self.plot:
            self.frame_files = []


    def import_ground_truth(self, episode_index):
        # map_dir = f'maps_medium'
        # map_list = os.listdir(map_dir)
        # map_index = episode_index % np.size(map_list)
        # ground_truth = (io.imread(map_dir + '/' + map_list[map_index], 1) * 255).astype(int)

        # ground_truth = block_reduce(ground_truth, 2, np.min)

        # robot_cell = np.array(np.nonzero(ground_truth == 208))
        # robot_cell = np.array([robot_cell[1, 10], robot_cell[0, 10]])

        # ground_truth = (ground_truth > 150) | ((ground_truth <= 80) & (ground_truth >= 50))
        # ground_truth = ground_truth * 254 + 1

        # return ground_truth, robot_cell
        self.test = False
        if self.test:
            map_dir = f'maps_test'
        else:
            map_dir = f'maps_medium'
        map_list = os.listdir(map_dir)
        map_index = episode_index % np.size(map_list)
        ground_truth = (io.imread(map_dir + '/' + map_list[map_index], 1)).astype(int)

        ground_truth = block_reduce(ground_truth, 2, np.min)

        robot_cell = np.array(np.nonzero(ground_truth == 208))
        robot_cell = np.array([robot_cell[1, 10], robot_cell[0, 10]])

        ground_truth = (ground_truth > 150) | ((ground_truth <= 80) & (ground_truth >= 50))
        ground_truth = ground_truth * 254 + 1

        return ground_truth, robot_cell

    def update_robot_location(self, robot_location):
        self.robot_location = robot_location
        self.robot_cell = np.array([round((robot_location[0] - self.belief_origin_x) / self.cell_size),
                                    round((robot_location[1] - self.belief_origin_y) / self.cell_size)])

    def update_robot_belief(self, robot_cell):
        self.robot_belief = sensor_work(robot_cell, round(self.sensor_range / self.cell_size), self.robot_belief,
                                        self.ground_truth)
        
    def calculate_ind_nav_reward(self, astar_dist_cur_to_target, astar_dist_next_to_target, dist_to_target):
        reward = 0
        done = False
        reward -= 0.5
        reward += (astar_dist_cur_to_target - astar_dist_next_to_target) / (self.ground_truth.shape[0] * self.cell_size/10)
        # print(dist_to_target)
        # if dist_to_target <= 20:
        #     reward += 20
        #     done = True
        return reward

    def calculate_reward(self):
        reward = 0

        global_frontiers = get_frontier_in_map(self.belief_info)
        if global_frontiers.shape[0] == 0:
            delta_num = self.global_frontiers.shape[0]
        else:
            global_frontiers = global_frontiers.reshape(-1, 2)
            frontiers_to_check = global_frontiers[:, 0] + global_frontiers[:, 1] * 1j
            pre_frontiers_to_check = self.global_frontiers[:, 0] + self.global_frontiers[:, 1] * 1j
            frontiers_num = np.intersect1d(frontiers_to_check, pre_frontiers_to_check).shape[0]
            pre_frontiers_num = pre_frontiers_to_check.shape[0]
            delta_num = pre_frontiers_num - frontiers_num

        reward += delta_num / 200

        new_area = np.sum(self.robot_belief == 255) - np.sum(self.old_belief == 255)
        # reward += np.clip(new_area / 1000, 0.1, 0.5)

        self.global_frontiers = global_frontiers
        self.old_belief = deepcopy(self.robot_belief)

        return reward

    def check_done(self):
        if np.sum(self.ground_truth == 255) - np.sum(self.robot_belief == 255) <= 250:
            self.done = True

    def evaluate_exploration_rate(self):
        self.explored_rate = np.sum(self.robot_belief == 255) / np.sum(self.ground_truth == 255)

    def step(self, next_waypoint, agent_id):
        self.evaluate_exploration_rate()
        self.robot_locations[agent_id] = next_waypoint
        reward = 0
        cell = get_cell_position_from_coords(next_waypoint, self.belief_info)
        self.update_robot_belief(cell)
        # reward = self.calculate_reward(dist)

        return reward


