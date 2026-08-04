clc
close all
clear all
Screen('Preference', 'SkipSyncTests', 0);

%% Getting output file in case of psychtoolbox crash
% Specify the path and filename for the output text file
outputFile = 'output.txt';

% Open the output file for writing
outputFileID = fopen(outputFile, 'w');

% Redirect MATLAB output to the text file
diary(outputFile);

%% check FOV script results that you have written down


% if you have written that the right eye is = 1 : change_eye = 0

% if you have written that the right eye is = 0 : change_eye = 1

change_eye = 0; % you can change this parameter based on the results of FOV script

%% NOTE:
% press t to start --> this comes from the trigger box
% press space to finish --> you usually do not need to do this, unless
% there is something wrong with the run and you want to stop it prematurely

%% do not any thing below
%% code starts...
%_________________________________________________________________________%
%% run initialization
% change this according to what you want to presnt to the subject 
% run_id =1 --> movie 1A - left eye 
% run_id =2 --> movie 2A - right eye
% run_id =3 --> movie 1B - right eye 
% run_id =4 --> movie 2B - left eye
answer  = questdlg(sprintf([' Have you transfered the code used for the previous subejct?' ...
'\n Have you deleted the content of the Folder called "Results"? ' ...
'\n' ]), 'IMPORTANT STEP');

% Handle response
switch answer
    case 'Yes'
        disp([answer ' CONTINUE '])
    case 'No'
        warningMessage = sprintf('DO IT NOW!');
        uiwait(warndlg(warningMessage));
        return
    case 'Cancel'
        warningMessage = sprintf('DO IT NOW!');
        uiwait(warndlg(warningMessage));
        return
end
%__________________________________________________________________________%
% Subject initialization
% should be the same as what you used in the previous function
x           = inputdlg('Subject Initials')
comment     = x{1}
%__________________________________________________________________________%

y  = inputdlg(sprintf(['run Initialization\n'...
'\n 1  --> movie 1A - left eye ' ...
'\n 2  --> movie 2A - right eye' ...
'\n 3  --> movie 1B - right eye  ' ...
'\n 4  --> movie 2B - left eye' ...
'\n' ... 
'\n  enter the number and press OK']));

run_id= str2num(y{1})

%% Do not touch the rest of the code
% the only thing that you are allowed to change is the path and name of the
% movies 
resultdir = 'Results';

format long  
t = datestr(now,'mmmm-dd-yyyy_HH-MM-SS_AM')
save([resultdir '/' (t) '_Subject_is_' comment '_selected_run_id_' num2str(run_id)]) 

path=cd;
switch run_id 
    case 1
    % movie-eye % left eye should be stimulated
    moviename =('Movie1A.mp4');
    eye = change_eye
    Show_movie(moviename, eye)
case 2
    moviename = ('Movie2A.mp4');
    % movie-not(eye) % right eye should be stimulated
    eye= double(~change_eye)
    Show_movie( moviename, eye) 
case 3 
    moviename = ('Movie1B.mp4');
    eye = double(~change_eye)
    Show_movie(moviename, eye)
case 4
    moviename =  ('Movie2B.mp4');
    eye= change_eye
    Show_movie( moviename, eye) 
end