function Show_Movie(moviename,eye) % eye is where movie is being presented

white = [255 255 255];
gray = [128 128 128];
black = [0 0 0];
red= [255 0 0];
blue=[0 0 255];
fixRadius_inner = 0.15;
white_line_size = 2;    % width of line in the middle of fixation spot
AssertOpenGL;
Screen('Preference', 'SkipSyncTests', 1);


% Wait until user releases keys on keyboard:
KbReleaseWait;

KbName('UnifyKeyNames');

% Setup key mapping:
space=KbName('Space');
shift=KbName('RightShift');

% Parameter Set-Up

screen = min(Screen('Screens'));
% Stereo - mode is 4
[win, windowrect] = Screen(screen, 'OpenWindow', gray, [], [], [], 4); 	% Limit screen to just a window in the top left screen corner. 
HideCursor

% calculate dimentions of the screen
x0      = windowrect(1);
y0      = windowrect(2);
xEnd    = windowrect(3);
yEnd    = windowrect(4);
screenWidth = (xEnd-x0);
screenHeight= (yEnd-y0);
[centerX, centerY] = RectCenter(windowrect);

FOV =30
PixelperDegree = 800/FOV;
size_radius_degree=0.25; %% this is something we might need to change 

Radius  = round(size_radius_degree*PixelperDegree)
fixRadius_inner = round(PixelperDegree * fixRadius_inner);

fixRect = CenterRectOnPointd([0 0 Radius*2 Radius*2],centerX,centerY);
fixRect_inner=CenterRectOnPointd([0 0 fixRadius_inner*2 fixRadius_inner*2],centerX,centerY);

Priority(MaxPriority(win));
%% Wait Screen --> The experiment will start shortly
Screen('SelectStereoDrawBuffer', win, eye);
Screen('FillRect', win,black);
Screen('TextSize',win,20);

Screen('SelectStereoDrawBuffer', win, double(~eye));
Screen('FillRect', win,black);
Screen('TextSize',win,20);

textMessage = 'The experiment will start shortly';
textRect = Screen(win, 'TextBounds', textMessage);
textWidth = textRect(3) - textRect(1);
textHeight = textRect(4) - textRect(2);

% First eye
Screen('SelectStereoDrawBuffer', win, eye);
Screen('DrawText', win, textMessage,...
    centerX-(textWidth/2), centerY-(textHeight/2), white, black);
% Second eye
Screen('SelectStereoDrawBuffer', win, double(~eye));

Screen('DrawText', win, textMessage,...
    centerX-(textWidth/2), centerY-(textHeight/2), white, black);

% Flip info to the real window
Screen('Flip', win);
%% keyboard cheking 
%Let matlab command window ignore incoming keypresses
KbName('UnifyKeyNames');
psychtoolbox_forp_id=0;
%% start after a t has been pressed
try
    % Open movie file:
    Screen('SelectStereoDrawBuffer', win, eye);
    [movie movieduration fps w h count] = Screen('OpenMovie', win, moviename);
    
    Screen('SelectStereoDrawBuffer', win, eye);
    % Start playback engine:
    Screen('PlayMovie', movie, 1);
    
    % Playback loop: Runs until end of movie or keypress:
    keysOfInterest=zeros(1,256);
    keysOfInterest(KbName('t'))=1;
    % only look for t as trigger
    KbQueueCreate(psychtoolbox_forp_id, keysOfInterest);	
    KbQueueStart;
    
    [keyPress, keyTime, keyID] = KbCheck(-1);  
    oldKeyID = keyID;
    KbQueueWait
    while 1

      %%%% PAUSE CODE %%%%%%%
      [keyIsDown,secs,keyCode]=KbCheck;
      if (keyIsDown==1 && keyCode(space))
            % Stop playback:
            Priority(0);
            Screen('PlayMovie', movie, 0);
            
            % Close movie:
            Screen('CloseMovie', movie);
            
            % Close Screen, we're done:
            sca;
      end

      % Wait for next movie frame, retrieve texture handle to it
      Screen('SelectStereoDrawBuffer', win, eye);
      tex = Screen('GetMovieImage', win, movie);
          
      % Valid texture returned? A negative value means end of movie reached:
      if tex<=0
        % We're done, break out of loop:
        break;
      end
          
      % Draw the new texture immediately to screen:
      Screen('SelectStereoDrawBuffer', win, eye);
      Screen('DrawTexture', win, tex);
  
      Screen('SelectStereoDrawBuffer', win, eye);
      Screen('FillOval', win, blue, fixRect);
      Screen('FillOval', win, red, fixRect_inner);   
      Screen('DrawLine', win, white, fixRect(1), centerY,fixRect(3), centerY, white_line_size);
      Screen('DrawLine', win, white, centerX, fixRect(2),centerX, fixRect(4), white_line_size);


      % Update display:
      Screen('Flip', win);
          
      % Release texture:
      Screen('Close', tex);
    end
    
    % Stop playback:
    Priority(0);
    Screen('PlayMovie', movie, 0);
    
    % Close movie:
    Screen('CloseMovie', movie);
    
    % Close Screen, we're done:
    sca;
    ShowCursor
    
catch %#ok<CTCH>
    Priority(0);
    sca;
    ShowCursor
    psychrethrow(psychlasterror);
end