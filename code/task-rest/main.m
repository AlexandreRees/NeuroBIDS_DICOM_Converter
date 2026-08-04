% Clear all variables and parameters in MATLAB 
clc
close all
clear all 
Screen('Preference', 'SkipSyncTests', 0);
%__________________________________________________________________________%
%Stimulus parameters
fixRadius = 0.25; %fixation dot radius in degrees
trs=320; % number of TRs
white_line_size = 2;    % width of line in the middle of fixation spot
%__________________________________________________________________________%
eye=1
absMinIndex = 0;
absMaxIndex = 255;
black   = [absMinIndex      absMinIndex         absMinIndex];
white   = [absMaxIndex      absMaxIndex         absMaxIndex];
%% Open screen
AssertOpenGL;
try
    % Here we call some default settings for setting up Psychtoolbox
    PsychDefaultSetup(2);
    screens=Screen('Screens');
    screenNumber=min(screens);

    stereoMode=4
    [windowPtr, windowRect]=Screen('OpenWindow', screenNumber,black, [], [], [], stereoMode);

    %% Psychtoolbox setup code comes here
    HideCursor;
    %Let matlab command window ignore incoming keypresses
    KbName('UnifyKeyNames');

    psychtoolbox_forp_id=-1;
    Devices = PsychHID('Devices');
    disp(Devices);
    for i=1:size(Devices,2)
        psychtoolbox_forp_id=i;
        break;
    end
    if psychtoolbox_forp_id==-1
        error('No FORP-Device detected on your system');
    end
    psychtoolbox_forp_id=0;
    
    keysOfInterest=zeros(1,256);
	keysOfInterest(KbName('t'))=1;
	% only look for t as trigger
	KbQueueCreate(psychtoolbox_forp_id, keysOfInterest);	
	KbQueueStart;
    
    [keyPress, keyTime, keyID] = KbCheck(-1);
    oldKeyID = keyID;
%__________________________________________________________________________%
    %% Calculate screen and pixel dimensions
    x0      = windowRect(1);
    y0      = windowRect(2);
    xEnd    = windowRect(3);
    yEnd    = windowRect(4);
    screenWidth = (xEnd-x0);
    screenHeight= (yEnd-y0);
    [centerX, centerY] = RectCenter(windowRect);
    %__________________________________________________________________________%
    %% changed according to visua-stim device characteristics
    degPerPix =30/800;
    pixPerDeg = 800/30;    
    %% Compute interframe interval and frames per second
    Priority(0);
    %% Some window related parameters 
	fixRadius = round(pixPerDeg * fixRadius);
    stimRadius = [screenWidth screenHeight];
	diameter = stimRadius;
	radius = diameter/2;
    %% Create the textures now that we have the diameter, screenprops,

    gratingRect = CenterRectOnPointd([0 0 diameter(1) diameter(2)],centerX,centerY);
    framePoly = [
        centerX-fixRadius centerY-fixRadius;
        centerX-fixRadius centerY-radius(2);
        centerX+fixRadius centerY-radius(2);
        centerX+fixRadius centerY-fixRadius;
        centerX+radius(1) centerY-fixRadius;
        centerX+radius(1) centerY+fixRadius;
        centerX+fixRadius centerY+fixRadius;
        centerX+fixRadius centerY+radius(2);
        centerX-fixRadius centerY+radius(2);
        centerX-fixRadius centerY+fixRadius;
        centerX-radius(1) centerY+fixRadius;
        centerX-radius(1) centerY-fixRadius;
    ];
    fixBackRect=CenterRectOnPointd([0 0 fixRadius*2*3 fixRadius*2*3],centerX,centerY);
    fixRect=CenterRectOnPointd([0 0 fixRadius*2 fixRadius*2],centerX,centerY);

    %% Experiment starts
    Priority(MaxPriority(windowPtr));
    HideCursor
    %% Wait Screen --> The experiment will start shortly
    Screen('SelectStereoDrawBuffer', windowPtr, eye);
    Screen('FillRect', windowPtr,black);
    Screen('SelectStereoDrawBuffer', windowPtr, double(~eye));
    Screen('FillRect', windowPtr,black);

    Screen('TextSize',windowPtr,20);
    textMessage = 'The experiment will start shortly';
    textRect = Screen(windowPtr, 'TextBounds', textMessage);
    textWidth = textRect(3) - textRect(1);
    textHeight = textRect(4) - textRect(2);
    
    % First eye
    Screen('SelectStereoDrawBuffer', windowPtr, eye);
    Screen('DrawText', windowPtr, textMessage,...
        centerX-(textWidth/2), centerY-(textHeight/2), white, black);
   
    % Second eye
    Screen('SelectStereoDrawBuffer', windowPtr, double(~eye));
    Screen('DrawText', windowPtr, textMessage,...
        centerX-(textWidth/2), centerY-(textHeight/2), white, black);

    % Flip info to the real window
    Screen('Flip', windowPtr);
    %__________________________________________________________________________%
    % Plot empty background - stimulated eye
    Screen('SelectStereoDrawBuffer', windowPtr, eye);
    Screen('FillRect', windowPtr, black);
	fixRect=CenterRectOnPointd([0 0 fixRadius*2 fixRadius*2],centerX,centerY);
    % Plot fixation spot - stimulated eye
    %Screen('FillOval', windowPtr, white, fixRect); % this is a simple
    %circle 
    Screen('DrawLine',  windowPtr,white, fixRect(1), centerY,fixRect(3), centerY, white_line_size);
    Screen('DrawLine', windowPtr,white, centerX, fixRect(2),centerX, fixRect(4), white_line_size);

    %% Wait for trigger
    KbQueueWait;
    % non-stimulated eye
    Screen('SelectStereoDrawBuffer', windowPtr, double(~eye)) ;% stimulated eye
    Screen('FillRect', windowPtr, black);
    %Screen('FillOval', windowPtr, white, fixRect);
    Screen('DrawLine',  windowPtr, white,fixRect(1), centerY,fixRect(3), centerY, white_line_size);
    Screen('DrawLine',  windowPtr, white,centerX, fixRect(2),centerX, fixRect(4), white_line_size);
    Screen('DrawingFinished', windowPtr);
    % Flip info to the real window
    Screen('Flip', windowPtr);        
    
    KbName('UnifyKeyNames');
    escapeKey = KbName('Escape');
    rep=0;
    while 1
        [keyIsDown,secs,keyCode]=KbCheck;       
      if (keyIsDown==1 && keyCode(KbName('t')))          
          rep=rep+1;
          KbReleaseWait
          if rep==trs
            Priority(0);
            % Close Screen, we're done:
            sca;
            ShowCursor
            break;
          end
      end
      %%%% PAUSE CODE %%%%
      if (keyIsDown==1 && keyCode(escapeKey))
            % Stop image:
            Priority(0);
            % Close Screen, we're done:
            sca;
            ShowCursor
            break
      end
    end
end