#!/usr/bin/env python3

#Imports
import rospy
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import Twist
from std_srvs.srv import Empty
from gazebo_msgs.msg import ModelState
from gazebo_msgs.srv import SetModelState
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import json
import numpy as np
import random
import math

class Move():
    twists = {
        "right": [0.2, -0.95],
        "left": [0.2, 0.95],
        "forward": [0.25, 0.001]
    }

    scan = None
    ranges = None

    mode = "train"

    startPoses = [(-1.75, 1.8, 0), (1.5, -1, 0), (1.5, 1, 1)]

    def __init__(self, mode="train"):
        Move.mode = mode
        self.init_node()
        self.init_services()
        self.init_publisher()
        self.init_subscriber()
        if Move.mode == "train":
            self.learn()
        elif Move.mode == "test":
            self.run()
    

    def init_services(self):
        rospy.wait_for_service("/gazebo/reset_world")
        try:
            self.reset_world = rospy.ServiceProxy("/gazebo/reset_world", Empty)
        except:
            rospy.loginfo("Unable to initiate reset world service")
            raise
        
        rospy.wait_for_service("/gazebo/set_model_state")
        try:
            self.set_state = rospy.ServiceProxy("/gazebo/set_model_state", SetModelState)
        except:
            rospy.loginfo("Unable to initiate set model state service")
            raise
        
        rospy.wait_for_service("/gazebo/pause_physics")
        try:
            self.pause_physics = rospy.ServiceProxy("/gazebo/pause_physics", Empty)
        except:
            rospy.loginfo("unable to initiate pause physics service")
            raise
        
        rospy.wait_for_service("gazebo/unpause_physics")
        try:
            self.unpause_physics = rospy.ServiceProxy("/gazebo/unpause_physics", Empty)
        except:
            rospy.loginfo("Unable to initiate unpause physics service")
            raise

        rospy.loginfo("services set up")
    

    def init_node(self):
        rospy.init_node("wallflower")
    

    def init_publisher(self):
        self.pub = rospy.Publisher("cmd_vel", Twist, queue_size=1)
    

    def init_subscriber(self):
        self.sub = rospy.Subscriber("/scan", LaserScan, self.callback)
    

    def publishTwist(self, twister):
        t = Twist()
        t.linear.x = twister[0]
        t.linear.y = 0
        t.linear.z = 0
        t.angular.x = 0
        t.angular.y = 0
        t.angular.z = twister[1]
        self.pub.publish(t)
    

    def makeModelState(self, pos):
        model_msg = ModelState()
        model_msg.model_name = "turtlebot3_waffle"
        model_msg.pose.position.x = pos[0]
        model_msg.pose.position.y = pos[1]
        model_msg.pose.position.z = 0
        model_msg.pose.orientation.x = 0
        model_msg.pose.orientation.y = 0
        model_msg.pose.orientation.z = 0
        model_msg.pose.orientation.w = pos[2]
        return model_msg
    

    def plot_learning(self, x, y, num_plots):
        #y is a list containing lists of individual data points. 
        fig, axs = plt.subplots(num_plots)
        fig.suptitle("Learning")
        for i in range(len(axs)):
            axs[i].plot(x[i], y[i])
        
        plt.savefig("Learning_Rates.pdf")
        plt.close()
        

    def split_range(self):
        for i,r in enumerate(Move.ranges):
            if r > 3.5:
                Move.ranges[i] = 3.6
        
        front = min([f for f in Move.ranges[0:44]]+[r for r in Move.ranges[314:359]])
        left = min([l for l in Move.ranges[44:134]])

        return (front, left)
    
    
    def get_table(self, filename):
        with open(filename, "r") as f:
            q = json.load(f)
        return q
    

    def save_table(self, table, filename):
        with open(filename, "w") as f:
            json.dump(table, f, indent=4)
    

    def getStringState(self, state, cmin, mmin, fmin):
        res = ""
        if cmin <= state[0] <= mmin:
            res += "forward: close, "
        elif mmin <= state[0] <= fmin:
            res += "forward: medium, "
        elif fmin <= state[0] <= 4:
            res += "forward: far, "
        
        if cmin <= state[1] < mmin:
            res += "left: close"
        elif mmin <= state[1] < fmin:
            res += "left: medium"
        elif fmin <= state[1] <= 4:
            res += "left: far"
        
        return res
    

    def updateQValue(self, reward, Q, old_state, new_state, action, new_action=None, strategy="sarsa", alpha=0.1, gamma=0.9):
        if strategy == "sarsa" and new_action:
            temp_diff = reward + gamma*((Q[new_state][new_action]))
        else:
            temp_diff = reward + gamma*(max(Q[new_state].values()))
        
        Q[old_state][action] = Q[old_state][action] + alpha*(temp_diff - Q[old_state][action])
    

    def calculate_reward(self, state, mmin, fmin):
        reward = 0
        if state[1] < mmin or state[1] >= fmin or state[0] < mmin:
            reward = -1
        
        return reward
    

    def rewardState(self, mmin, fmin):
        state = self.split_range()
        reward = self.calculate_reward(state, mmin, fmin)
        state = self.getStringState(state, 0, mmin, fmin)
        return reward, state
    
    
    def epoch(self, Q, eps):
        steps, counter, total, correct, val = 0, 0, 0, 0, 0
        T = 10
        termination = False
        Move.scan = None

        while not Move.scan and not rospy.is_shutdown():
            rospy.sleep(0.1)

        options = [self.makeModelState(pos) for pos in self.startPoses]
        self.set_state(np.random.choice(options))
        self.publishTwist([0,0])

        reward, state = self.rewardState(0.5, 0.75)

        if random.random() < eps:
            action = np.random.choice(list(Q[state].keys()))
        else:
            action = max(Q[state], key=Q[state].get)
        
        self.publishTwist(Move.twists[action])

        while not termination and not rospy.is_shutdown():
            rospy.sleep(0.1)
            self.pause_physics()

            steps += 1

            reward, newState = self.rewardState(0.5, 0.75)

            if "left: far" in newState:
                counter += 1
            else:
                counter = 0
            if counter == 150:
                #counter = 0
                if total: 
                    val = correct/total
                termination = True
            
            for d in Move.ranges:
                if not rospy.is_shutdown():
                    if d < 0.2:
                        reward = -15
                        if total:
                            val = correct/total
                        
                        termination = True
            
            if steps == 800:
               # steps = 0
                if total:
                    val = correct/total
                termination = True
            
            if random.random() < eps:
                s = sum([math.exp(a/T) for a in Q[newState].values()])
                p = [math.exp(x/T)/s for x in Q[newState].values()]
                new_action = np.random.choice(list(Q[newState].keys()), p=p)
            
            else:
                new_action = max(Q[newState], key=Q[newState].get)
                if state == "forward: close, right: far, left: close" or state == "forward: medium, right: far, left: close" or state=="forward: medium, right: far, left: medium":
                    total += 1
                    if new_action == "right":
                        correct += 1
            
            self.unpause_physics()
            self.publishTwist(self.twists[new_action])
#            self.pause_physics()
            self.updateQValue(reward, Q, state, newState, action, new_action=new_action, strategy="sarsa")
            action = new_action
            state = newState
        
        return val, total
    

    def learn(self):
        eps = 0.9
        duration = 500
        data = []
        dataEpisodes = 0

        for e in range(duration):
            if not rospy.is_shutdown():

                rospy.loginfo("Episode #" + str(e))

                Q = self.get_table("minimalQ.json")
                x, total = self.epoch(Q, eps)
                if total > 2:
                    data.append(x)
                    dataEpisodes += 1
                    self.plot_learning([dataEpisodes], [data])
                
                self.save_table(Q, "minimalQ.json")
               # if episode%50 == 0:
                #    rospy.loginfo("Demo starting....")
                 #   self.runFile()
                  #  rospy.loginfo("Demo complete")
                
                eps -= 1.2*(0.8)/duration
                rospy.sleep(0.1)
    

    def runFile(self):
        steps = 0
        termination = False
        Move.scan = None

        Q = self.get_table("minimalQ.json")
        rospy.loginfo("Table loaded")

        reward, state = self.rewardState(0.5, 0.75)

        action = max(Q[state], key=Q[state].get)
        self.publishTwist(Move.twists[action])

        while not termination and not rospy.is_shutdown():
            self.pause_physics()
            rospy.sleep(0.1)
            steps += 1

            reward, newState = self.rewardState(0.5, 0.75)

            for d in Move.ranges:
                if not rospy.is_shutdown():
                    if d < 0.2:
                        termination = True
            
            if steps >= 800:
                termination = True
            
            state = newState
            action = max(Q[state], key=Q[state].get)

            self.unpause_physics()
            self.publishTwist(self.twists[action])
    

    def run(self):
        duration = 100

        for episode in range(duration):
            if not rospy.is_shutdown():
                self.runFile()
    

    def callback(self, dist):
        Move.scan = True
        Move.ranges = list(dist.ranges)





if __name__ == "__main__":
    m = Move(mode="train")