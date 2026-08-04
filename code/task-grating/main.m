% Clear all variables and parameters in MATLAB 
clc
close all
clear all 
sca

%__________________________________________________________________________%
% Define resuls directory 
% There should exists a folder named "Results"
resultdir = './Results';
%__________________________________________________________________________%
% load shuffeled order of runs
% estimate which fMRI run it should correspond to
runs_random = load([resultdir '/runs_random.mat']);
runs_random = runs_random.runs_random;
run_number  = runs_random(1);
fMRI_number = 6 - length(runs_random) + 1
%__________________________________________________________________________%
% Subject initialization
% should be the same as what you used in the previous function
x           = inputdlg('Subject Initials')
comment     = x{1}
       
% stop the program if they introduced no initials                          
if isempty(comment)
  warningMessage = sprintf('\nApparently you do not want to continue!');
  uiwait(warndlg(warningMessage));
  return
end
%__________________________________________________________________________%
stimOrder      = 3;    % 3 random - %2 reverse - %1 not reverse
%__________________________________________________________________________%
paradigmNumber = 2;    % DO NOT TOUCH - IT SHOULD BE 2
%__________________________________________________________________________%
% colors
grey = [137 137 137];
black=[0 0 0];
%__________________________________________________________________________%
white_line_size = 2;    % width of line in the middle of fixation spot
color_poly = [162 162 162];
%__________________________________________________________________________%
%% run description
%% after FOV run if you have this result:
%% if eye = 1 is the right eye in stereo mode 4 --> below the order of eye should be 1 0
%% else it should be 0 1 
if run_number <= 3
    eye            = 1;
    text           = [ comment ' has his/her right eye  stimulated - fMRI run is ' num2str(fMRI_number)];
else
    eye            = 0;
    text           = [ comment ' has his/her left eye  stimulated - fMRI run is '  num2str(fMRI_number)];
end
%__________________________________________________________________________%
% Give info to the operator and wait for his validation
start_ask = inputdlg(sprintf([text '   \nEnter 1 if it is okay to continue']))
start_ask_yes_no = start_ask{1}        % subject initials 

if start_ask_yes_no ~= '1'
  warningMessage = sprintf('\nApparently you do not want to continue!');
  uiwait(warndlg(warningMessage));
  return
end
%% change eye - if needed
% check with subject - if reveresed, uncomment this 
%eye = double(~eye);
%% Allow some timing error
Screen('Preference', 'SkipSyncTests', 1);
%% Save input parameters
scan.comment = comment;
%% File specifc Parameters
%load in params
presentStimParams
%% List of conditions
conditionNone	= 0;
conditionStim	= 1;
conditionEnd	= 2;
%% Chosse current paradigm and save it
switch paradigmNumber
    case 2
        paradigm = runParadigmFinal;
end               
stim = generateStimulus(paradigmNumber);
%% Open screen
AssertOpenGL;
try
    % Here we call some default settings for setting up Psychtoolbox
    PsychDefaultSetup(2);

    %Define default oldgammatable in case catch block is called too early
    %oldgammatable = repmat(linspace(0,1,256)',[1 3]);

    screens=Screen('Screens');
    screenNumber=min(screens);

    stereoMode=4
    [windowPtr, windowRect]=Screen('OpenWindow', screenNumber,grey, [], [], [], stereoMode);

    %Enable alpha blending with proper blend-function.We need it for drawing of smoothed points:
    Screen('BlendFunction', windowPtr,GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

    %% Psychtoolbox setup code comes here
    HideCursor;
    %Let matlab command window ignore incoming keypresses
    KbName('UnifyKeyNames');
    
    psychtoolbox_forp_id=-1;
    if paradigmNumber ~= 0
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
    end
    
    keysOfInterest=zeros(1,256);
	keysOfInterest(KbName('t'))=1;
	% only look for t as trigger
	KbQueueCreate(psychtoolbox_forp_id, keysOfInterest);	
	KbQueueStart;
    
    [keyPress, keyTime, keyID] = KbCheck(-1);
    oldKeyID = keyID;
%__________________________________________________________________________%
    %Set Timestamp counter [actualtime Condition; ...]
    vbl = [];
%__________________________________________________________________________%
    %% Calculate screen and pixel dimensions
    x0      = windowRect(1);
    y0      = windowRect(2);
    xEnd    = windowRect(3);
    yEnd    = windowRect(4);
    screenWidth = (xEnd-x0);
    screenHeight= (yEnd-y0);
    [centerX, centerY] = RectCenter(windowRect);

    scan.windowRect = windowRect;
	%__________________________________________________________________________%
	%degPerCm = (2*atan(screenDiagonalSize/(2*viewingDistance))*180/pi)/screenDiagonalSize;
    %degPerPix = degPerCm * (screenDiagonalSize/sqrt(screenWidth^2+screenHeight^2));    
    %pixPerDeg = 1/degPerPix;  
    %__________________________________________________________________________%
    %% changed according to visua-stim device characteristics
    degPerPix =30/800;
    pixPerDeg = 800/30;
    %% Save old LUT, define new LUT and define some colors
    %absmax, absmin and absmean luminance and derived colors are absolute,
    %independend of contrast
    %all intensities in [relmin,relmax] scale with contrast setting

    absMinIndex = 0;
    absMaxIndex = 255;
    absMeanIndex= 137;
    black   = [absMinIndex      absMinIndex         absMinIndex];
    white   = [absMaxIndex      absMaxIndex         absMaxIndex];
    gray    = [absMeanIndex     absMeanIndex        absMeanIndex];
    red     = [absMaxIndex      absMinIndex         absMinIndex];
    blue    = [absMinIndex      absMinIndex         absMaxIndex];

    %% Compute interframe interval and frames per second
    Priority(MaxPriority(windowPtr));
    fps=Screen('FrameRate',windowPtr);
    ifi=Screen('GetFlipInterval', windowPtr);
    if fps==0
        fps=1/ifi;
    end
    Priority(0);
    scan.ifi = ifi;
    %% Some window related parameters 

	fixRadius = round(pixPerDeg * fixRadius);
    fixRadius_inner = round(pixPerDeg * fixRadius_inner);
    stimRadius = [screenWidth screenHeight];

    screenProperties.ifi = ifi;
    screenProperties.degPerPix = degPerPix;
    screenProperties.window = windowPtr;
    
	diameter = stimRadius;
	radius = diameter/2;
    %% **Loading stimulus**
    
    Screen('TextSize',windowPtr,20);
    textMessage = 'Loading stimulus';
    textRect = Screen(windowPtr, 'TextBounds', textMessage);
    textWidth = textRect(3) - textRect(1);
    textHeight = textRect(4) - textRect(2);

    % First eye
    Screen('SelectStereoDrawBuffer', windowPtr, eye);
    Screen('DrawText', windowPtr, textMessage,centerX-(textWidth/2), centerY-(textHeight/2), white, gray);

    % Second eye
    Screen('SelectStereoDrawBuffer', windowPtr,double(~eye));
    Screen('DrawText', windowPtr, textMessage,centerX-(textWidth/2), centerY-(textHeight/2), white, gray);

    % Flip info to the real window
    Screen('Flip', windowPtr);
    %% Create the textures now that we have the diameter, screenprops,
    for s = 1:length(stim)
        stim{s}.createTextures(diameter,screenProperties)
    end
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
    fixRect_inner=CenterRectOnPointd([0 0 fixRadius_inner*2 fixRadius_inner*2],centerX,centerY);
    %% Experiment starts
    Priority(MaxPriority(windowPtr));
    %% Wait Screen --> The experiment will start shortly
    Screen('FillRect', windowPtr,grey);
    Screen('TextSize',windowPtr,20);
    textMessage = 'The experiment will start shortly';
    textRect = Screen(windowPtr, 'TextBounds', textMessage);
    textWidth = textRect(3) - textRect(1);
    textHeight = textRect(4) - textRect(2);
    
    % First eye
    Screen('SelectStereoDrawBuffer', windowPtr, eye);
    Screen('DrawText', windowPtr, textMessage,...
        centerX-(textWidth/2), centerY-(textHeight/2), white, gray);
   
    % Second eye
    Screen('SelectStereoDrawBuffer', windowPtr, double(~eye));
    Screen('DrawText', windowPtr, textMessage,...
        centerX-(textWidth/2), centerY-(textHeight/2), white, gray);

    % Flip info to the real window
    Screen('Flip', windowPtr);
    %Screen('BlendFunction', windowPtr, 'GL_SRC_ALPHA', 'GL_ONE_MINUS_SRC_ALPHA');
%__________________________________________________________________________%
	scan.runs = {};

	for run = 1:runs
	    %% Prepare first conditionamplitude
	    state = conditionNone;
	    laststate = conditionNone;
	    trigger = true;
        currentConditionStartTime = 0;
	    currentStimulus = 0;

        % Plot empty background - stimulated eye
        Screen('SelectStereoDrawBuffer', windowPtr, eye);
	    Screen('FillRect', windowPtr, gray);
		fixRect=CenterRectOnPointd([0 0 fixRadius*2 fixRadius*2],centerX,centerY);
        fixRect_inner=CenterRectOnPointd([0 0 fixRadius_inner*2 fixRadius_inner*2],centerX,centerY);
        
        % Plot fixation spot - stimulated eye
        Screen('FillOval', windowPtr, blue, fixRect);
        Screen('FillOval', windowPtr, red, fixRect_inner);
        Screen('DrawLine', windowPtr, white, fixRect(1), centerY,fixRect(3), centerY, white_line_size);
        Screen('DrawLine', windowPtr, white, centerX, fixRect(2),centerX, fixRect(4), white_line_size);
    
        
	    % Plot empty background - non-stimulated eye

        Screen('SelectStereoDrawBuffer', windowPtr, double(~eye)) ;% stimulated eye  
        Screen('FillRect', windowPtr, black);
	   
	    %% Wait for trigger
	    scan.runs{run}.triggerTimes = KbQueueWait;
	    
	    %% MAIN LOOP
	    while state~=conditionEnd
	        %% Flip screen and estimate time of next screen;
	        vbl         = [vbl ; [Screen('Flip', windowPtr) , state, trigger]];
	        t           = (vbl(end,1)-vbl(1,1));
	        nextT       = (vbl(end,1)-vbl(1,1))+ifi;
	        framecount  = floor((vbl(end,1) - vbl(1,1))/ifi) + 1;
	        scan.runs{run}.vbl = vbl;
	
	        timeProperties.t = t;
	        timeProperties.framecount = framecount;

	        %% Drawing commands
	       switch state
	            case conditionStim %% condition stim

                    Screen('SelectStereoDrawBuffer', windowPtr, eye);    

	                stimulusTexture = stim{stimRunIndices(run,mod(currentStimulus,length(stim))+1,stimOrder)}.getNextTexture(timeProperties);
	                Screen('DrawTexture', windowPtr,stimulusTexture,[],gratingRect,0,0); 
  
                     % non-stimulated eye
                    Screen('SelectStereoDrawBuffer', windowPtr, double(~eye)) ;% stimulated eye  
                    Screen('FillRect', windowPtr, black);       
                
   
               case conditionNone %% condition rest 
                   % stimulated eye
                   Screen('SelectStereoDrawBuffer', windowPtr, eye);    
                   Screen('FillRect', windowPtr, gray);
     
                   Screen('SelectStereoDrawBuffer', windowPtr, double(~eye)); % non-stimulated eye
                   Screen('FillRect', windowPtr, black);       
            
	        end
	      %% fixation spot on the screen 
           % stimulated eye

            Screen('SelectStereoDrawBuffer', windowPtr, eye);    
            Screen('FramePoly', windowPtr, color_poly,framePoly); % put horizontal and vertical lines on the stimulated eye - all the time
            Screen('FillOval', windowPtr, blue, fixRect);
            Screen('FillOval', windowPtr, red, fixRect_inner);
            Screen('DrawLine', windowPtr, white, fixRect(1),centerY,fixRect(3),centerY, white_line_size);
            Screen('DrawLine', windowPtr, white, centerX, fixRect(2),centerX, fixRect(4), white_line_size);
   
            % stimulated eye
            Screen('SelectStereoDrawBuffer', windowPtr, eye);    
	        Screen('DrawingFinished', windowPtr);

            % non-stimulated eye
            Screen('SelectStereoDrawBuffer', windowPtr, double(~eye)) ;% stimulated eye  
            Screen('DrawingFinished', windowPtr);
	        %% Process key Input % Check for trigger
	        [ pressed, firstPress]=KbQueueCheck;	% Collect keyboard events since KbQueueStart was invoked
	        if pressed && firstPress(KbName('t'))
	            scan.runs{run}.triggerTimes = [scan.runs{run}.triggerTimes firstPress(KbName('t'))];
	            trigger = true;
	        else
	            trigger = false;
            end        	        
	        [keyPress, keyTime, keyID] = KbCheck(-1);
	        if any(keyID-oldKeyID)
	            keyPressID = keyID;
	            oldKeyID = keyID;
	        else
	            keyPressID = zeros(size(keyID));
	        end
	        %% Update state
	        laststate = state;
	        state = paradigm(min(find(paradigm(:,1) > length(scan.runs{run}.triggerTimes)))-1,2);
	        if isempty(state) || keyPressID(KbName('Escape'))
	            state = conditionEnd;
	        end
	        if laststate == conditionStim && state ~= conditionStim
	            currentStimulus = currentStimulus+1;
            end
            if length(scan.runs{run}.triggerTimes) == runParadigmFinal(end,1)
                runs_random = runs_random(2:end);
                save Results/runs_random
            end
	        %% Initialize new state
	        if state~=laststate
	            currentConditionStartTime = nextT;
	        end
        end
        Screen('SelectStereoDrawBuffer', windowPtr, double(~eye)); % non-stimulated eye
        Screen('FillRect', windowPtr, black);

		Screen('Flip', windowPtr);
	end
    %% Clean up
    Priority(0);
    %Screen('LoadNormalizedGammaTable', windowPtr, oldgammatable);
    Screen('CloseAll');
    ShowCursor;
    filename = mfilename('fullpath');
    fid = fopen([filename '.m']);
    lineNumber = 0;
    while true
        lineNumber = lineNumber + 1;
        tLine = fgetl(fid);
        if ~ischar(tLine)
            break;
        else
            scan.program{lineNumber} = tLine;
        end
    end
    fclose(fid);
    timeend = datestr(now,'mmmm-dd-yyyy_HH-MM-SS_AM')
    save([resultdir '/' timeend '__scan_info_for_subject_' comment '__selected_run_is_' num2str(run_number) ...
        '__fmri_number_is' num2str(fMRI_number) '.mat'], 'scan');


catch
    %catch errors
    Priority(0);
    %Screen('LoadNormalizedGammaTable', windowPtr, oldgammatable);
    Screen('CloseAll');
    ShowCursor;
    filename = mfilename('fullpath');
    fid = fopen([filename '.m']);
    lineNumber = 0;
    while true
        lineNumber = lineNumber + 1;
        tLine = fgetl(fid);
        if ~ischar(tLine)
            break;
        else
            scan.program{lineNumber} = tLine;
        end
    end
    fclose(fid);
    
    err = lasterror;
    disp(err.stack);
    rethrow(lasterror);
    timecatch = datestr(now,'mmmm-dd-yyyy_HH-MM-SS_AM')
    save([resultdir '/catch_' timecatch '_scan_info_for_subject_' comment '__selected_run_is_' num2str(run_number) ...
        '__fmri_number_is' num2str(fMRI_number) '.mat'], 'scan');
end
