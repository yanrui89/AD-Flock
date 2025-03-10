import numpy as np
import torch
import matplotlib.pyplot as plt
from copy import deepcopy

from env import Env
from agent import Agent
from parameter import *
from utils import *
from model import PolicyNet
from local_node_manager_quadtree import Local_node_manager

if not os.path.exists(gifs_path):
    os.makedirs(gifs_path)


class Multi_agent_worker:
    def __init__(self, meta_agent_id, policy_net, global_step, device='cpu', save_image=False):
        self.meta_agent_id = meta_agent_id
        self.global_step = global_step
        self.save_image = save_image
        self.device = device

        self.env = Env(global_step, plot=self.save_image)
        self.n_agent = N_AGENTS
        self.local_node_manager = Local_node_manager(plot=self.save_image, modality="Local")
        self.ground_truth_node_manager = Local_node_manager(plot=False, modality="Groundtruth")

        self.ground_truth_agent = Agent(100, policy_net, self.ground_truth_node_manager, self.device, False)
        self.ground_truth_agent.update_target(self.env.target)
        self.ground_truth_agent.update_ground_truth_graph(self.env.ground_truth_info)

        self.robot_list = [Agent(i, policy_net, self.local_node_manager, self.device, self.save_image) for i in
                           range(N_AGENTS)]

        self.episode_buffer = []
        self.perf_metrics = dict()
        for i in range(15):
            self.episode_buffer.append([])

    def run_episode(self):
        done = False
        for robot in self.robot_list:
            robot.update_target(self.env.target)
            robot.update_graph(self.env.belief_info, deepcopy(self.env.robot_locations[robot.id]))
            
        for robot in self.robot_list:    
            robot.update_planning_state(self.env.robot_locations)

        for i in range(MAX_EPISODE_STEP):
            selected_locations = []
            dist_list = []
            next_node_index_list = []
            for robot in self.robot_list:
                local_observation = robot.get_local_observation()
                robot.save_observation(local_observation)

                next_location, next_node_index, action_index = robot.select_next_waypoint(local_observation)
                robot.save_action(action_index)
                node = robot.local_node_manager.local_nodes_dict.find((robot.location[0], robot.location[1]))
                check = np.array(node.data.neighbor_list)
                assert next_location[0] + next_location[1] * 1j in check[:, 0] + check[:, 1] * 1j, print(next_location,
                                                                                                         robot.location,
                                                                                                         node.data.neighbor_list)
                assert next_location[0] != robot.location[0] or next_location[1] != robot.location[1]

                selected_locations.append(next_location)
                dist_list.append(np.linalg.norm(next_location - robot.location))
                next_node_index_list.append(next_node_index)

            selected_locations = np.array(selected_locations).reshape(-1, 2)
            arriving_sequence = np.argsort(np.array(dist_list))
            selected_locations_in_arriving_sequence = np.array(selected_locations)[arriving_sequence]

            for j, selected_location in enumerate(selected_locations_in_arriving_sequence):
                solved_locations = selected_locations_in_arriving_sequence[:j]
                while selected_location[0] + selected_location[1] * 1j in solved_locations[:, 0] + solved_locations[:, 1] * 1j:
                    id = arriving_sequence[j]
                    nearby_nodes = self.robot_list[id].local_node_manager.local_nodes_dict.nearest_neighbors(
                        selected_location.tolist(), 25)
                    for node in nearby_nodes:
                        coords = node.data.coords
                        if coords[0] + coords[1] * 1j in solved_locations[:, 0] + solved_locations[:, 1] * 1j:
                            continue
                        selected_location = coords
                        break

                    selected_locations_in_arriving_sequence[j] = selected_location
                    selected_locations[id] = selected_location

            reward_list = []
            robot_location = []
            robot_dist = 0
            ind_done_list = []
            for robot, next_location, next_node_index in zip(self.robot_list, selected_locations, next_node_index_list):  #TODO: Need to think what to add in the reward
                self.env.step(next_location, robot.id)
                individual_reward = robot.utility[next_node_index] / 50
                _, astar_dist_cur_to_target = self.ground_truth_agent.local_node_manager.a_star(robot.location, robot.target)
                _, astar_dist_next_to_target = self.ground_truth_agent.local_node_manager.a_star(next_location, robot.target)
                dist_to_target = np.linalg.norm(next_location - robot.target)
                robot_dist += dist_to_target
                ind_nav_rew = self.env.calculate_ind_nav_reward(astar_dist_cur_to_target, astar_dist_next_to_target, dist_to_target)
                # ind_done_list.append(ind_done)
                total_reward = individual_reward + ind_nav_rew
                reward_list.append(total_reward)
                robot_location.append(next_location)
                # Implement cohesion
                # FIXME Extract robot.location in an empty array

                # Compute the np.mean
                # Compute distance from np.mean
                # Penalise using distance**2

                robot.update_graph(self.env.belief_info, deepcopy(self.env.robot_locations[robot.id]))
            
            cohesion_reward_list = []
            # Implement cohesion

            # Calculate the centroid of the robot locations
            centroid = np.mean(selected_locations, axis=0)

            # Iterate through the selected locations and rewards to apply cohesion penalty
            for idx, (next_location, reward) in enumerate(zip(selected_locations, reward_list)):
                cohesion_penalty = np.linalg.norm(next_location - centroid)
                
                # Apply the cohesion penalty if it exceeds 1
                if cohesion_penalty > 1:
                    cohesion_reward_list.append((cohesion_penalty / 50))
                else:
                    cohesion_reward_list.append(0)


            # if self.robot_list[0].utility.sum() == 0: # FIXME change to check location of centroid to goal point
            #     done = True
            # if np.sum(ind_done) == self.n_agent:
            #     done = True
            # print(robot_dist/len(self.robot_list))
            check_condition = robot_dist/len(self.robot_list)
            if check_condition <= 1:
                done = True

            team_reward = self.env.calculate_reward() - 0.5
            if done:
                team_reward += 40

            for robot, reward, cohesion_reward in zip(self.robot_list, reward_list, cohesion_reward_list):
                robot.save_reward(reward + team_reward - cohesion_reward)
                robot.update_planning_state(self.env.robot_locations)
                robot.save_done(done)

            if self.save_image:
                self.plot_local_env(i, check_condition)

            if done:
                if self.save_image:
                    self.plot_local_env(i + 1, check_condition)
                break

        # save metrics
        self.perf_metrics['travel_dist'] = max([robot.travel_dist for robot in self.robot_list])
        self.perf_metrics['explored_rate'] = self.env.explored_rate
        self.perf_metrics['success_rate'] = done

        # save episode buffer
        for robot in self.robot_list:
            local_observation = robot.get_local_observation()
            robot.save_next_observations(local_observation)
            for i in range(len(self.episode_buffer)):
                self.episode_buffer[i] += robot.episode_buffer[i]

        # save gif
        if self.save_image:
            make_gif(gifs_path, self.global_step, self.env.frame_files, self.env.explored_rate)

    def plot_local_env(self, step, check_condition):
        plt.switch_backend('agg')
        plt.figure(figsize=(15, 5))
        plt.subplot(1, 2, 2)
        plt.imshow(self.env.robot_belief, cmap='gray')
        plt.axis('off')
        color_list = ['r', 'b', 'g', 'y']
        frontiers = get_frontier_in_map(self.env.belief_info)
        frontiers = get_cell_position_from_coords(frontiers, self.env.belief_info).reshape(-1, 2)
        target_cell = get_cell_position_from_coords(self.env.target, self.env.ground_truth_info).reshape(-1, 2)
        plt.scatter(target_cell[:,0], target_cell[:,1], c='b', marker='*', s=15)
        plt.scatter(frontiers[:, 0], frontiers[:, 1], c='r', s=5)
        for robot in self.robot_list:
            c = color_list[robot.id]
            robot_cell = get_cell_position_from_coords(robot.location, robot.global_map_info)
            plt.plot(robot_cell[0], robot_cell[1], c+'o', markersize=16, zorder=5)
            plt.plot((np.array(robot.trajectory_x) - robot.global_map_info.map_origin_x) / robot.cell_size,
                     (np.array(robot.trajectory_y) - robot.global_map_info.map_origin_y) / robot.cell_size, c,
                     linewidth=2, zorder=1)
            # for i in range(len(self.local_node_manager.x)):
            #   plt.plot((self.local_node_manager.x[i] - self.local_map_info.map_origin_x) / self.cell_size,
            #            (self.local_node_manager.y[i] - self.local_map_info.map_origin_y) / self.cell_size, 'tan', zorder=1)

        plt.subplot(1, 2, 1)
        plt.imshow(self.env.robot_belief, cmap='gray')
        plt.scatter(frontiers[:, 0], frontiers[:, 1], c='r', s=1)
        for robot in self.robot_list:
            c = color_list[robot.id]
            if robot.id == 0:
                nodes = get_cell_position_from_coords(robot.local_node_coords, robot.global_map_info)
                plt.imshow(robot.global_map_info.map, cmap='gray')
                plt.axis('off')
                plt.scatter(nodes[:, 0], nodes[:, 1], c=robot.utility, zorder=2)

            robot_cell = get_cell_position_from_coords(robot.location, robot.global_map_info)
            plt.plot(robot_cell[0], robot_cell[1], c+'o', markersize=12, zorder=5)

        plt.axis('off')
        plt.suptitle('Explored ratio: {:.4g}  Travel distance: {:.4g}      Target distance: {:.4g}'.format(self.env.explored_rate,
                                                                              max([robot.travel_dist for robot in
                                                                                   self.robot_list]), check_condition))
        plt.tight_layout()
        # plt.show()
        plt.savefig('{}/{}_{}_samples.png'.format(gifs_path, self.global_step, step), dpi=150)
        frame = '{}/{}_{}_samples.png'.format(gifs_path, self.global_step, step)
        self.env.frame_files.append(frame)
